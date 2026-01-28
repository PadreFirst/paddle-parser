import streamlit as st
import pandas as pd
import io

# --- Конфигурация страницы ---
st.set_page_config(page_title="Paddle Parser Pro", layout="wide")
st.title("📊 Paddle Analytics: Парсер транзакций")

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
    # (Выкидываем мусор типа draft/ready/canceled)
    df = df[df['status'] == 'completed'].copy()
    
    # 4. Считаем длительность подписки (Double Check по периоду)
    # Если дат нет (это OTP), результат будет NaT/NaN
    df['duration_days'] = (df['billing_period_ends_at'] - df['billing_period_starts_at']).dt.days

    # 5. Функция категоризации каждой строки
    def categorize(row):
        price_usd = row['balance_currency_total'] # Сумма, которая пришла нам (уже в USD)
        days = row['duration_days']
        sub_id = row.get('subscription_id')

        # --- ЛОГИКА OTP (Разовые) ---
        # Признак: нет ID подписки ИЛИ длительность не определена (0 или NaN)
        if pd.isna(sub_id) or pd.isna(days) or days == 0:
            # Разделяем OTP по цене (с запасом на курсовые разницы)
            if 10.0 <= price_usd < 20.0:
                return 'OTP Small ($14.99)'
            elif 20.0 <= price_usd < 35.0:
                return 'OTP Big ($24.99)'
            else:
                return 'OTP Other'

        # --- ЛОГИКА ПОДПИСОК ---
        
        # Шаг А: Определяем Период по дням (календарь не врет)
        period_name = 'Unknown'
        if 1 <= days <= 10:
            period_name = 'Week'
        elif 20 <= days <= 35:
            period_name = 'Month'
        elif 80 <= days <= 100:
            period_name = '3 Months'
        else:
            return 'Other Sub'

        # Шаг Б: Определяем Триал по цене (Full Week/Month не нужны)
        if period_name == 'Week':
            if price_usd < 7.5:  # Триал ~$4.99
                return 'Trial Week'
            
        elif period_name == 'Month':
            if price_usd < 22.0:  # Триал ~$14.99 или $19.99
                return 'Trial Month'
            
        elif period_name == '3 Months':
            if price_usd < 45.0:  # Триал ~$29.99
                return 'Trial 3 Months'

        # Full Week/Month/3 Months -> Other Sub
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
            # Сортируем категории: сначала Trial Week/Month/3 Months, потом остальные
            preferred_order = ['Trial Week', 'Trial Month', 'Trial 3 Months']
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
            
            # Фиксированный порядок колонок: Trial Week -> Trial Month -> Trial 3 Months -> остальные
            preferred_order = ['Trial Week', 'Trial Month', 'Trial 3 Months']
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

