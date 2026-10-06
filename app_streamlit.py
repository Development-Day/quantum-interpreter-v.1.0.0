"""
Streamlit-версия QuantumInterpreter.

Запуск:
    pip install streamlit
    streamlit run app_streamlit.py
"""

import streamlit as st
import numpy as np
import matplotlib.pyplot as plt

from quantum_interpreter import (
    QuantumInterpreter, Config,
    _bloch_coords, _draw_bloch_2d, _draw_bloch_mixed
)

st.set_page_config(page_title="QuantumInterpreter", layout="wide")
st.title("QuantumInterpreter — веб-песочница")

# --- Боковая панель: параметры ---
with st.sidebar:
    st.header("Параметры")
    num_qubits = st.slider("Кубитов", 1, 12, 4)
    matrix_size = st.slider("Размер матрицы", 100, 3000, 1000, step=100)
    rot_key = st.slider("ROT-ключ", -50, 50, 12)

    if st.button("Применить"):
        st.session_state.qi = QuantumInterpreter(
            Config(num_qubits=num_qubits,
                   matrix_size=matrix_size,
                   rot_key=rot_key)
        )
        st.success("Параметры применены")

# --- Инициализация ---
if "qi" not in st.session_state:
    st.session_state.qi = QuantumInterpreter(Config())

qi: QuantumInterpreter = st.session_state.qi

# --- Ввод скрипта ---
default_script = """config num_qubits 4
config matrix_size 500

h 0
x 1
y 2
z 3

set_portal_q a 0
set_portal_q b 1
entangle_portals a b

summary

measure_qubit 0
print_state"""

script = st.text_area("Скрипт", default_script, height=250)

col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    if st.button("▶ Выполнить"):
        qi.output.clear()
        qi.execute(script)
        st.success(f"Выполнено. Папка: {qi.run_dir}")
with col2:
    if st.button("Визуализации"):
        qi.save_all_visualizations()
        st.success("PNG сохранены (кроме summary)")
with col3:
    if st.button("Сводный график"):
        path = qi.summary_plot()
        st.success(f"Сводка #{qi.summary_counter}: {path}")

# --- Вывод ---
st.subheader("Вывод")
for line in qi.output:
    st.text(line)

# --- Все summary_*.png ---
summary_files = sorted(qi.run_dir.glob("summary_*.png"))
if summary_files:
    st.subheader(f"Сводные графики ({len(summary_files)})")
    for path in summary_files:
        st.image(str(path), caption=path.name, use_column_width=True)

# --- Визуализация: 3 графика ---
st.subheader("Ключевые визуализации")
cols = st.columns(3)

with cols[0]:
    try:
        state = qi._get_statevector()
        x, y, z = _bloch_coords(state, 0)
        norm = np.sqrt(x**2 + y**2 + z**2)
        fig, ax = plt.subplots(figsize=(4, 4))
        if norm < 1e-6:
            _draw_bloch_mixed(ax, title="Кубит 0")
        else:
            _draw_bloch_2d(ax, x, y, z, title="Кубит 0")
        st.pyplot(fig)
        plt.close(fig)
    except Exception as e:
        st.warning(f"Блох: {e}")

with cols[1]:
    if qi.entropy_history:
        labels = [l for l, _ in qi.entropy_history]
        vals = [v for _, v in qi.entropy_history]
        fig, ax = plt.subplots(figsize=(4, 4))
        ax.bar(range(len(vals)), vals, color="purple", alpha=0.7)
        ax.set_xticks(range(len(vals)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("S (бит)")
        ax.set_title("Энтропия")
        st.pyplot(fig)
        plt.close(fig)
    else:
        st.info("Нет данных энтропии")

with cols[2]:
    try:
        state = qi._get_statevector()
        probs = np.abs(np.asarray(state)) ** 2
        fig, ax = plt.subplots(figsize=(4, 4))
        ax.bar(range(len(probs)), probs, color="teal", alpha=0.8)
        ax.set_title("Амплитуды")
        ax.set_xlabel("|i⟩")
        st.pyplot(fig)
        plt.close(fig)
    except Exception as e:
        st.warning(f"Амплитуды: {e}")

# --- Отчёт ---
with st.expander("Полный отчёт"):
    st.text(qi.report())