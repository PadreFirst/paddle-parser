import streamlit as st
import pandas as pd
import io

# --- Конфигурация страницы ---
st.set_page_config(page_title="Paddle Parser Pro", layout="wide")
st.title("📊 Paddle Analytics: Парсер транзакций")

# --- КОНФИГУРАЦИЯ: Price ID для новых продуктов ---
# AB тест: недельный триал $4.99 → месячная подписка $29.99
AB_TEST_OTP_PRICE = 'pri_01kh1355651wfrxjef8bqjf6c7'
AB_TEST_SUB_PRICE = 'pri_01kh1fdhza697vde9285837ccr'

# Апселлы (разовые покупки)
UPSELL_PAIN_SHIELD_PRICE = 'pri_01khnrc611h5wdg986vkxrv3ga'    # $14.99 Pain Shield
UPSELL_BELLY_BURNER_PRICE = 'pri_01khnrvmxd0srxcbmgq05b0gb5'   # $14.99 Belly Burner System
UPSELL_BUNDLE_PRICE = 'pri_01khnrb54wqk49x7jy92gcw88r'          # $19.99 бандл (оба вместе)


# --- ГЛАВНАЯ ЛОГИКА (Бизнес-правила) ---
def process_paddle_file(file_obj):
    # 1. Загрузка
    df = pd.read_csv(file_obj)
    
    # 2. Приводим даты в порядок (Double Check по датам)
    date_cols = ['created_at', 'billing_period_starts_at', 'billing_period_ends_at']
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    # 3. Оставляем только успешные оплаты
    df = df[df['status'] == 'completed'].copy()
    
    # 4. Считаем длительность подписки
    df['duration_days'] = (df['billing_period_ends_at'] - df['billing_period_starts_at']).dt.days

    # 5. Функция категоризации каждой строки
    def categorize(row):
        price_usd = row['balance_currency_total']
        days = row['duration_days']
        sub_id = row.get('subscription_id')
        price_ids = str(row.get('price_id_list', ''))

        # --- AB ТЕСТ: триал $4.99 (неделя) → $29.99 (месяц) ---
        # Триал: в price_id_list два ID (OTP + подписка), период 7 дней
        if AB_TEST_OTP_PRICE in price_ids and AB_TEST_SUB_PRICE in price_ids:
            return 'Trial Week (AB)'
        # Конверсия: только подписочный price_id, 28-дневный период
        if price_ids == AB_TEST_SUB_PRICE:
            return 'Month $29.99 (AB)'

        # --- АПСЕЛЛЫ (разовые покупки по price_id) ---
        if UPSELL_PAIN_SHIELD_PRICE in price_ids:
            return 'Upsell Pain Shield ($14.99)'
        if UPSELL_BELLY_BURNER_PRICE in price_ids:
            return 'Upsell Belly Burner ($14.99)'
        if UPSELL_BUNDLE_PRICE in price_ids:
            return 'Upsell Bundle ($19.99)'

        # --- ЛОГИКА OTP (Разовые, не попавшие в апселлы) ---
        if pd.isna(sub_id) or pd.isna(days) or days == 0:
            if 10.0 <= price_usd < 20.0:
                return 'OTP Small ($14.99)'
            elif 20.0 <= price_usd < 35.0:
                return 'OTP Big ($24.99)'
            else:
                return 'OTP Other'

        # --- ЛОГИКА ПОДПИСОК ---
        period_name = 'Unknown'
        if 1 <= days <= 10:
            period_name = 'Week'
        elif 20 <= days <= 35:
            period_name = 'Month'
        elif 80 <= days <= 100:
            period_name = '3 Months'
        else:
            return 'Other Sub'

        if period_name == 'Week':
            if price_usd < 7.5:
                return 'Trial Week'
            
        elif period_name == 'Month':
            if price_usd < 22.0:
                return 'Trial Month'
            
        elif period_name == '3 Months':
            if price_usd < 45.0:
                return 'Trial 3 Months'

        return 'Other Sub'

    # Применяем функцию ко всем строкам
    df['category'] = df.apply(categorize, axis=1)
    
    # Добавляем просто дату (без времени) для группировки
    df['date_only'] = df['created_at'].dt.date
    
    return df

# --- ИНТЕРФЕЙС (Веб-морда) ---

uploaded_file = st.file_uploader("📂 Перетащи сюда CSV файл (transactions)", type=['csv'])

if uploaded_file:
    try:
        # Парсим
        df = process_paddle_file(uploaded_file)
        
        # --- Блок фильтров ---
        st.divider()
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("1. Выбери период")
            # Находим мин/макс даты в файле
            min_d, max_d = df['date_only'].min(), df['date_only'].max()
            
            # Дейтпикер
            date_range = st.date_input(
                "Диапазон дат",
                value=(min_d, max_d),
                min_value=min_d,
                max_value=max_d
            )
            
        with col2:
            st.subheader("2. Типы транзакций")
            preferred_order = [
                'Trial Week', 'Trial Week (AB)', 'Trial Month', 'Trial 3 Months',
                'Month $29.99 (AB)',
                'Upsell Pain Shield ($14.99)', 'Upsell Belly Burner ($14.99)', 'Upsell Bundle ($19.99)',
            ]
            all_cats_raw = df['category'].unique().tolist()
            all_cats = [c for c in preferred_order if c in all_cats_raw] + sorted([c for c in all_cats_raw if c not in preferred_order])
            selected_cats = st.multiselect(
                "Что показывать?", 
                options=all_cats, 
                default=all_cats
            )

        # Применяем фильтры
        if len(date_range) == 2:
            mask = (
                (df['date_only'] >= date_range[0]) & 
                (df['date_only'] <= date_range[1]) & 
                (df['category'].isin(selected_cats))
            )
            df_filtered = df[mask]
            
            # --- РЕЗУЛЬТАТЫ ---
            st.divider()
            
            # Сводная таблица (Pivot)
            pivot = df_filtered.pivot_table(
                index='date_only', 
                columns='category', 
                values='id', 
                aggfunc='count', 
                fill_value=0
            )
            
            preferred_order = [
                'Trial Week', 'Trial Week (AB)', 'Trial Month', 'Trial 3 Months',
                'Month $29.99 (AB)',
                'Upsell Pain Shield ($14.99)', 'Upsell Belly Burner ($14.99)', 'Upsell Bundle ($19.99)',
            ]
            existing_cols = [c for c in preferred_order if c in pivot.columns]
            other_cols = [c for c in pivot.columns if c not in preferred_order]
            pivot = pivot[existing_cols + sorted(other_cols)]
            
            # 1. Красивая таблица для просмотра
            st.subheader(f"Результат ({len(df_filtered)} транзакций)")
            st.dataframe(pivot, use_container_width=True)
            
            # 2. Текстовое поле для Excel/Google Sheets
            st.subheader("📋 Для копирования в Google Sheets")
            st.caption("Нажми внутри, выдели всё (Ctrl+A), скопируй (Ctrl+C) и вставь в Гугл Таблицу (Ctrl+V)")
            
            # Превращаем таблицу в TSV (Tab Separated Values) - это идеально для вставки
            tsv_data = pivot.to_csv(sep='\t')
            st.text_area("Копируй отсюда:", value=tsv_data, height=300)
            
    except Exception as e:
        st.error(f"Ошибка: {e}")
        st.info("Убедись, что ты загружаешь именно файл Transactions Export из Paddle.")

else:
    st.info("⬅️ Загрузи файл, чтобы начать магию.")

