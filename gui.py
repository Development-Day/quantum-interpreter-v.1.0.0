"""
GUI для QuantumInterpreter на Tkinter — расширенная версия.

Возможности:
  • Меню: Файл, Правка, Вид, Помощь.
  • Копировать / вставить / вырезать / отменить / повторить.
  • Горячие клавиши: Ctrl+C/V/X/Z/Y/A, Ctrl+Enter, F5, Ctrl+S, Ctrl+O, Ctrl+F.
  • Контекстное меню (правый клик) в полях ввода и вывода.
  • Панель быстрых команд (H, X, Y, Z, RX, RY, RZ, CX, CZ, SWAP, Measure,
    Entangle, GHZ, Print, QASM, Сводка).
  • Панель «Описание процесса» — человеко-понятное объяснение каждого шага.
  • Статус-бар с текущими параметрами и последним сообщением.
  • Запуск скрипта в отдельном потоке — GUI не виснет.
  • 4 встроенных графика: Блох, Энтропия, Амплитуды, Матрица.
  • Кнопка «Сводный график» — единый PNG 3×3 (нумеруется).
  • Zoom +/−/Сброс, экспорт графиков в PNG.
  • Светлая/тёмная тема.
  • Сохранение/загрузка скрипта и состояния (JSON).
  • Поиск по выводу (Ctrl+F).
  • Демо-скрипт по умолчанию + кнопка «Загрузить демо».

Запуск:
    python gui.py
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg,
    NavigationToolbar2Tk,
)

from quantum_interpreter import (
    QuantumInterpreter,
    Config,
    _bloch_coords,
    _draw_bloch_2d,
    _draw_bloch_mixed,
)

import warnings
warnings.filterwarnings(
    "ignore",
    message="Starting a Matplotlib GUI outside of the main thread",
    category=UserWarning,
)


# ============================================================
#  Демонстрационный скрипт по умолчанию
# ============================================================

DEMO_SCRIPT = """# ============================================
#  МАКСИМАЛЬНО НАГЛЯДНЫЙ СКРИПТ
#  Демонстрирует все возможности интерпретатора
# ============================================

# ---- 1. Конфигурация ----
config num_qubits 4
config matrix_size 500

# ============================================
#  ЭТАП 1: Заполняем матрицу 8 точками
# ============================================
config cursor_start 50,50
move 0 0
set_cell 5

config cursor_start 150,100
move 0 0
set_cell 10

config cursor_start 300,50
move 0 0
set_cell 15

config cursor_start 400,150
move 0 0
set_cell 20

config cursor_start 100,300
move 0 0
set_cell 25

config cursor_start 250,350
move 0 0
set_cell 30

config cursor_start 400,400
move 0 0
set_cell 35

config cursor_start 50,450
move 0 0
set_cell 40

# ============================================
#  ЭТАП 2: Два портала
# ============================================
config cursor_start 200,200
move 0 0
set_portal c1

config cursor_start 350,250
move 0 0
set_portal h0

# ============================================
#  ЭТАП 3: ROT-текст
# ============================================
flp12 "quantum demonstration"
flp12 "alive graphs"

# ============================================
#  ЭТАП 4: 4 разных вектора Блоха
# ============================================
h 0
x 1
y 2
z 3

bloch 0
bloch 1
bloch 2
bloch 3

# ============================================
#  ЭТАП 5: Двухкубитные гейты
# ============================================
cx 0 1
cz 2 3

# ============================================
#  ЭТАП 6: Повороты
# ============================================
ry 0 0.7854
ry 1 1.0472
ry 2 0.5236
ry 3 1.5708

bloch 0
bloch 1
bloch 2
bloch 3

# ============================================
#  ЭТАП 7: Запутанность
# ============================================
set_portal_q alpha 0
set_portal_q beta 1
entangle_portals alpha beta

bloch 0
bloch 1
bloch 2
bloch 3

# ============================================
#  ЭТАП 8: СВОДКА ДО ИЗМЕРЕНИЙ (богатая картина)
# ============================================
summary

# ============================================
#  ЭТАП 9: Измерения
# ============================================
measure_qubit 0
measure_qubit 1
measure_qubit 2
measure_qubit 3

# ============================================
#  ЭТАП 10: Финальный вывод
# ============================================
print_state
qasm
"""


# ============================================================
#  Вспомогательный виджет: Text с контекстным меню
# ============================================================

class TextWithMenu(tk.Text):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._build_menu()
        self.bind("<Button-3>", self._show_menu)
        self.bind("<Button-2>", self._show_menu)

    def _build_menu(self):
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Вырезать", accelerator="Ctrl+X",
                              command=lambda: self.event_generate("<<Cut>>"))
        self.menu.add_command(label="Копировать", accelerator="Ctrl+C",
                              command=lambda: self.event_generate("<<Copy>>"))
        self.menu.add_command(label="Вставить", accelerator="Ctrl+V",
                              command=lambda: self.event_generate("<<Paste>>"))
        self.menu.add_separator()
        self.menu.add_command(label="Выделить всё", accelerator="Ctrl+A",
                              command=self._select_all)
        self.menu.add_command(label="Очистить",
                              command=lambda: self.delete("1.0", "end"))

    def _select_all(self):
        self.tag_add("sel", "1.0", "end")
        self.mark_set("insert", "1.0")
        return "break"

    def _show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()


# ============================================================
#  Основной GUI
# ============================================================

class QuantumGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("QuantumInterpreter — GUI")
        self.root.geometry("1600x900")
        self.root.minsize(1200, 700)

        self.config = Config()
        self.qi = QuantumInterpreter(self.config)

        self.result_queue: queue.Queue = queue.Queue()
        self.theme = "light"

        self.status_var = tk.StringVar(
            value=f"Кубитов: {self.config.num_qubits} | "
                  f"Матрица: {self.config.matrix_size} | "
                  f"ROT-ключ: {self.config.rot_key}"
        )
        self.status_msg = tk.StringVar(value="Готово.")

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()

    # ---------------------------------------------------------- меню

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Открыть скрипт…", accelerator="Ctrl+O",
                              command=self.open_script)
        file_menu.add_command(label="Сохранить скрипт…", accelerator="Ctrl+S",
                              command=self.save_script)
        file_menu.add_separator()
        file_menu.add_command(label="Загрузить демо-скрипт",
                              command=self.load_demo_script)
        file_menu.add_separator()
        file_menu.add_command(label="Загрузить состояние…",
                              command=self.load_state)
        file_menu.add_command(label="Сохранить состояние…",
                              command=self.save_state)
        file_menu.add_separator()
        file_menu.add_command(label="Экспорт графиков в PNG…",
                              command=self.export_plots)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", accelerator="Alt+F4",
                              command=self.root.quit)
        menubar.add_cascade(label="Файл", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Отменить", accelerator="Ctrl+Z",
                              command=self._undo)
        edit_menu.add_command(label="Повторить", accelerator="Ctrl+Y",
                              command=self._redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Вырезать", accelerator="Ctrl+X",
                              command=self._cut)
        edit_menu.add_command(label="Копировать", accelerator="Ctrl+C",
                              command=self._copy)
        edit_menu.add_command(label="Вставить", accelerator="Ctrl+V",
                              command=self._paste)
        edit_menu.add_command(label="Выделить всё в командах",
                              accelerator="Ctrl+A",
                              command=self._select_all_input)
        edit_menu.add_separator()
        edit_menu.add_command(label="Найти в выводе…", accelerator="Ctrl+F",
                              command=self.find_in_output)
        menubar.add_cascade(label="Правка", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Очистить вывод",
                              command=self.clear_output)
        view_menu.add_command(label="Очистить команды",
                              command=lambda: self.txt_input.delete("1.0",
                                                                     "end"))
        view_menu.add_command(label="Очистить описание",
                              command=self.clear_process)
        view_menu.add_separator()
        view_menu.add_command(label="Zoom +",
                              command=lambda: self._zoom(1.2))
        view_menu.add_command(label="Zoom −",
                              command=lambda: self._zoom(1 / 1.2))
        view_menu.add_command(label="Сбросить Zoom",
                              command=self._reset_zoom)
        view_menu.add_separator()
        view_menu.add_command(label="Светлая тема",
                              command=lambda: self._set_theme("light"))
        view_menu.add_command(label="Тёмная тема",
                              command=lambda: self._set_theme("dark"))
        menubar.add_cascade(label="Вид", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Справка по командам",
                              command=self.show_help)
        help_menu.add_command(label="О программе",
                              command=lambda: messagebox.showinfo(
                                  "О программе",
                                  "QuantumInterpreter GUI\n"
                                  "Гибридная классическо-квантовая "
                                  "песочница на Qiskit.\n\n"
                                  "MIT License"))
        menubar.add_cascade(label="Помощь", menu=help_menu)

        self.root.config(menu=menubar)

    # ---------------------------------------------------------- layout

    def _build_layout(self):
        top = ttk.LabelFrame(self.root, text="Параметры")
        top.pack(fill="x", padx=8, pady=(8, 4))

        self.var_num_qubits = tk.IntVar(value=self.config.num_qubits)
        self.var_matrix_size = tk.IntVar(value=self.config.matrix_size)
        self.var_rot_key = tk.IntVar(value=self.config.rot_key)
        self.var_cursor_x = tk.IntVar(value=self.config.cursor_start[0])
        self.var_cursor_y = tk.IntVar(value=self.config.cursor_start[1])
        self.var_shots = tk.IntVar(value=self.config.shots)

        ttk.Label(top, text="Кубитов:").grid(row=0, column=0, padx=4, pady=4)
        ttk.Spinbox(top, from_=1, to=16, textvariable=self.var_num_qubits,
                    width=5).grid(row=0, column=1)

        ttk.Label(top, text="Матрица:").grid(row=0, column=2, padx=4)
        ttk.Spinbox(top, from_=50, to=5000, increment=50,
                    textvariable=self.var_matrix_size, width=7
                    ).grid(row=0, column=3)

        ttk.Label(top, text="ROT:").grid(row=0, column=4, padx=4)
        ttk.Spinbox(top, from_=-100, to=100,
                    textvariable=self.var_rot_key, width=5
                    ).grid(row=0, column=5)

        ttk.Label(top, text="Курсор X:").grid(row=0, column=6, padx=4)
        ttk.Spinbox(top, from_=0, to=5000,
                    textvariable=self.var_cursor_x, width=6
                    ).grid(row=0, column=7)

        ttk.Label(top, text="Y:").grid(row=0, column=8, padx=4)
        ttk.Spinbox(top, from_=0, to=5000,
                    textvariable=self.var_cursor_y, width=6
                    ).grid(row=0, column=9)

        ttk.Label(top, text="Shots:").grid(row=0, column=10, padx=4)
        ttk.Spinbox(top, from_=1, to=10000,
                    textvariable=self.var_shots, width=6
                    ).grid(row=0, column=11)

        ttk.Button(top, text="Применить",
                   command=self.apply_config).grid(row=0, column=12, padx=8)

        quick = ttk.LabelFrame(self.root, text="Быстрые команды")
        quick.pack(fill="x", padx=8, pady=4)

        quick_buttons = [
            ("H 0",          "h 0\n"),
            ("X 0",          "x 0\n"),
            ("Y 0",          "y 0\n"),
            ("Z 0",          "z 0\n"),
            ("RX 0 π/2",     "rx 0 1.5708\n"),
            ("RY 0 π/2",     "ry 0 1.5708\n"),
            ("RZ 0 π/2",     "rz 0 1.5708\n"),
            ("CX 0 1",       "cx 0 1\n"),
            ("CZ 0 1",       "cz 0 1\n"),
            ("SWAP 0 1",     "swap 0 1\n"),
            ("Measure 0",    "measure_qubit 0\n"),
            ("Entangle a b", "set_portal_q a 1\nset_portal_q b 2\n"
                             "entangle_portals a b\n"),
            ("GHZ 0-2",      "h 0\ncx 0 1\ncx 1 2\n"),
            ("Print state",  "print_state\n"),
            ("QASM",         "qasm\n"),
            ("Сводка",       "summary\n"),
        ]
        for i, (label, cmd) in enumerate(quick_buttons):
            ttk.Button(quick, text=label, width=14,
                       command=lambda c=cmd: self.insert_command(c)
                       ).grid(row=0, column=i, padx=2, pady=2)

        middle = ttk.PanedWindow(self.root, orient="horizontal")
        middle.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.LabelFrame(middle, text="Команды")
        middle.add(left, weight=1)

        self.txt_input = TextWithMenu(left, height=15,
                                      font=("Consolas", 10),
                                      undo=True, wrap="none")
        self.txt_input.pack(side="left", fill="both", expand=True,
                            padx=4, pady=4)

        in_scroll = ttk.Scrollbar(left, orient="vertical",
                                  command=self.txt_input.yview)
        in_scroll.pack(side="right", fill="y")
        self.txt_input.configure(yscrollcommand=in_scroll.set)

        self.txt_input.insert("1.0", DEMO_SCRIPT)

        btns = ttk.Frame(left)
        btns.pack(fill="x", padx=4, pady=4)
        ttk.Button(btns, text="▶ Выполнить",
                   command=self.run_script).pack(side="left", padx=2)
        ttk.Button(btns, text="Визуализации",
                   command=self.show_visualizations).pack(side="left", padx=2)
        ttk.Button(btns, text="Сводный график",
                   command=self.show_summary).pack(side="left", padx=2)
        ttk.Button(btns, text="Загрузить демо",
                   command=self.load_demo_script).pack(side="left", padx=2)
        ttk.Button(btns, text="Очистить вывод",
                   command=self.clear_output).pack(side="left", padx=2)
        ttk.Button(btns, text="Загрузить сост.",
                   command=self.load_state).pack(side="left", padx=2)
        ttk.Button(btns, text="Сохранить сост.",
                   command=self.save_state).pack(side="left", padx=2)

        right = ttk.LabelFrame(middle, text="Вывод")
        middle.add(right, weight=1)

        self.txt_output = TextWithMenu(right, height=15,
                                       font=("Consolas", 10),
                                       wrap="word", state="normal")
        self.txt_output.pack(side="left", fill="both", expand=True,
                             padx=4, pady=4)

        out_scroll = ttk.Scrollbar(right, orient="vertical",
                                   command=self.txt_output.yview)
        out_scroll.pack(side="right", fill="y")
        self.txt_output.configure(yscrollcommand=out_scroll.set)

        out_btns = ttk.Frame(right)
        out_btns.pack(fill="x", padx=4, pady=4)
        ttk.Button(out_btns, text="Копировать всё",
                   command=self.copy_output).pack(side="left", padx=2)
        ttk.Button(out_btns, text="Сохранить в файл…",
                   command=self.save_output).pack(side="left", padx=2)
        ttk.Button(out_btns, text="Найти…",
                   command=self.find_in_output).pack(side="left", padx=2)

        proc = ttk.LabelFrame(middle, text="Описание процесса")
        middle.add(proc, weight=2)

        self.txt_process = tk.Text(proc, height=15, font=("Segoe UI", 10),
                                   wrap="word", state="normal",
                                   bg="#fafafa")
        self.txt_process.pack(side="left", fill="both", expand=True,
                              padx=4, pady=4)

        proc_scroll = ttk.Scrollbar(proc, orient="vertical",
                                    command=self.txt_process.yview)
        proc_scroll.pack(side="right", fill="y")
        self.txt_process.configure(yscrollcommand=proc_scroll.set)

        self.txt_process.tag_configure("title",
                                       font=("Segoe UI", 11, "bold"),
                                       foreground="#003366")
        self.txt_process.tag_configure("step",
                                       font=("Segoe UI", 10, "bold"),
                                       foreground="#004080")
        self.txt_process.tag_configure("what",
                                       font=("Segoe UI", 10),
                                       foreground="#222222")
        self.txt_process.tag_configure("why",
                                       font=("Segoe UI", 10, "italic"),
                                       foreground="#555555")
        self.txt_process.tag_configure("effect",
                                       font=("Segoe UI", 10),
                                       foreground="#006633")

        proc_btns = ttk.Frame(proc)
        proc_btns.pack(fill="x", padx=4, pady=4)
        ttk.Button(proc_btns, text="Очистить описание",
                   command=self.clear_process).pack(side="left", padx=2)
        ttk.Button(proc_btns, text="Объяснить скрипт",
                   command=self.explain_current_script).pack(side="left",
                                                             padx=2)

        bottom = ttk.LabelFrame(self.root, text="Визуализация")
        bottom.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        self.fig, self.axes = plt.subplots(1, 4, figsize=(16, 4))
        self.fig.subplots_adjust(left=0.05, right=0.98,
                                 top=0.9, bottom=0.15, wspace=0.3)

        self.canvas = FigureCanvasTkAgg(self.fig, master=bottom)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        nav_frame = ttk.Frame(bottom)
        nav_frame.pack(fill="x")
        self.toolbar = NavigationToolbar2Tk(self.canvas, nav_frame)
        self.toolbar.update()

        zoom_frame = ttk.Frame(bottom)
        zoom_frame.pack(fill="x", padx=4, pady=2)
        ttk.Button(zoom_frame, text="Zoom +",
                   command=lambda: self._zoom(1.2)).pack(side="left", padx=2)
        ttk.Button(zoom_frame, text="Zoom −",
                   command=lambda: self._zoom(1 / 1.2)).pack(side="left",
                                                              padx=2)
        ttk.Button(zoom_frame, text="Сброс",
                   command=self._reset_zoom).pack(side="left", padx=2)
        ttk.Button(zoom_frame, text="Экспорт PNG",
                   command=self.export_plots).pack(side="left", padx=2)

        status = ttk.Frame(self.root)
        status.pack(fill="x", side="bottom")
        ttk.Label(status, textvariable=self.status_var,
                  anchor="w").pack(side="left", padx=8, pady=2)
        ttk.Label(status, textvariable=self.status_msg,
                  anchor="e").pack(side="right", padx=8, pady=2)

        self._welcome_process()

    # ---------------------------------------------------------- горячие клавиши

    def _bind_shortcuts(self):
        self.root.bind("<Control-Return>", lambda e: self.run_script())
        self.root.bind("<F5>", lambda e: self.run_script())
        self.root.bind("<Control-s>", lambda e: self.save_script())
        self.root.bind("<Control-o>", lambda e: self.open_script())
        self.root.bind("<Control-f>", lambda e: self.find_in_output())
        self.root.bind("<Control-z>", lambda e: self._undo())
        self.root.bind("<Control-y>", lambda e: self._redo())
        self.root.bind("<Control-a>", lambda e: self._select_all_input())

    def _undo(self):
        try:
            self.txt_input.edit_undo()
        except tk.TclError:
            pass

    def _redo(self):
        try:
            self.txt_input.edit_redo()
        except tk.TclError:
            pass

    def _cut(self):
        self.txt_input.event_generate("<<Cut>>")

    def _copy(self):
        self.txt_input.event_generate("<<Copy>>")

    def _paste(self):
        self.txt_input.event_generate("<<Paste>>")

    def _select_all_input(self):
        self.txt_input.tag_add("sel", "1.0", "end")
        return "break"

    def insert_command(self, cmd: str):
        self.txt_input.insert("end", cmd)
        self.txt_input.see("end")
        self.status_msg.set(f"Добавлено: {cmd.strip()}")

    def load_demo_script(self):
        self.txt_input.delete("1.0", "end")
        self.txt_input.insert("1.0", DEMO_SCRIPT)
        self.status_msg.set("Демо-скрипт загружен.")

    def copy_output(self):
        text = self.txt_output.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_msg.set("Вывод скопирован в буфер обмена.")

    def save_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_output.get("1.0", "end-1c"))
            self.status_msg.set(f"Вывод сохранён → {path}")

    def open_script(self):
        path = filedialog.askopenfilename(
            filetypes=[("Text", "*.txt"), ("Python", "*.py"),
                       ("All", "*.*")],
        )
        if path:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.txt_input.delete("1.0", "end")
            self.txt_input.insert("1.0", content)
            self.status_msg.set(f"Скрипт ← {path}")

    def save_script(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_input.get("1.0", "end-1c"))
            self.status_msg.set(f"Скрипт → {path}")

    def find_in_output(self):
        needle = simpledialog.askstring("Поиск", "Что найти в выводе?")
        if not needle:
            return
        self.txt_output.tag_remove("find", "1.0", "end")
        idx = "1.0"
        count = 0
        while True:
            idx = self.txt_output.search(needle, idx, stopindex="end",
                                         nocase=True)
            if not idx:
                break
            end = f"{idx}+{len(needle)}c"
            self.txt_output.tag_add("find", idx, end)
            idx = end
            count += 1
        self.txt_output.tag_config("find", background="yellow",
                                   foreground="black")
        self.status_msg.set(f"Найдено вхождений: {count}")

    def apply_config(self):
        try:
            self.config.num_qubits = int(self.var_num_qubits.get())
            self.config.matrix_size = int(self.var_matrix_size.get())
            self.config.rot_key = int(self.var_rot_key.get())
            self.config.cursor_start = (int(self.var_cursor_x.get()),
                                        int(self.var_cursor_y.get()))
            self.config.shots = int(self.var_shots.get())
        except (tk.TclError, ValueError) as e:
            messagebox.showerror("Ошибка", f"Некорректное значение: {e}")
            return

        self.qi = QuantumInterpreter(self.config)
        self.status_var.set(
            f"Кубитов: {self.config.num_qubits} | "
            f"Матрица: {self.config.matrix_size} | "
            f"ROT: {self.config.rot_key} | "
            f"Shots: {self.config.shots}"
        )
        self.status_msg.set("Параметры применены.")
        self.refresh_plots()

    def run_script(self):
        script = self.txt_input.get("1.0", "end")
        self.qi = QuantumInterpreter(self.config)
        self.txt_output.delete("1.0", "end")
        self.status_msg.set("Выполняется…")

        def worker():
            try:
                self.qi.execute(script)
            except AttributeError as e:
                self.result_queue.put(
                    ("error",
                     f"{e}\n\n"
                     "Похоже, вы используете Qiskit 1.x. "
                     "Метод QuantumCircuit.qasm() удалён. "
                     "Пропатчите quantum_interpreter.py.")
                )
            except Exception as e:
                self.result_queue.put(("error", str(e)))
                return
            self.result_queue.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            status, msg = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_queue)
            return

        if status == "error":
            self.txt_output.insert("end", f"[ОШИБКА] {msg}\n")
            self.status_msg.set("Ошибка выполнения.")
        else:
            for line in self.qi.output:
                self.txt_output.insert("end", line + "\n")
            self.status_msg.set(f"Готово. Папка: {self.qi.run_dir}")
            self.refresh_plots()
            self.explain_current_script()

    def clear_output(self):
        self.txt_output.delete("1.0", "end")
        self.status_msg.set("Вывод очищен.")

    def clear_process(self):
        self.txt_process.delete("1.0", "end")
        self.status_msg.set("Описание очищено.")

    def show_visualizations(self):
        try:
            self.qi.save_all_visualizations()
        except Exception as e:
            self.txt_output.insert("end", f"[ОШИБКА визуализации] {e}\n")
            return
        self.refresh_plots()
        self.txt_output.insert(
            "end",
            "\nВизуализации (кроме summary) сохранены в PNG.\n"
        )
        self.status_msg.set("Визуализации сохранены.")

    def show_summary(self):
        """Сохраняет сводный PNG 3×3 (нумеруется) и показывает его в нижней панели."""
        try:
            path = self.qi.summary_plot()
        except Exception as e:
            self.txt_output.insert("end", f"[ОШИБКА сводки] {e}\n")
            return

        self.txt_output.insert("end", f"\nСводный график → {path}\n")
        self.status_msg.set(f"Сводка → {path}")

        try:
            from matplotlib.image import imread
            img = imread(path)
            for ax in self.axes:
                ax.clear()
            self.axes[0].imshow(img)
            self.axes[0].axis("off")
            self.axes[0].set_title(f"Сводка #{self.qi.summary_counter}")
            for i in range(1, 4):
                self.axes[i].axis("off")
            self.fig.tight_layout()
            self.canvas.draw()
        except Exception as e:
            self.txt_output.insert("end", f"[предпросмотр] {e}\n")

    def _welcome_process(self):
        self.txt_process.insert("end", "QuantumInterpreter — Описание процесса\n",
                                "title")
        self.txt_process.insert(
            "end",
            "\nЭто окно показывает пошаговое объяснение каждой команды:\n"
            "  • Что делает команда.\n"
            "  • Зачем она нужна.\n"
            "  • Как она влияет на состояние системы.\n\n"
            "Нажмите «▶ Выполнить» — и здесь появится разбор вашего скрипта.\n\n"
            "Также можно нажать «Объяснить скрипт» для разбора без запуска.\n",
            "what"
        )

    def explain_current_script(self):
        self.txt_process.delete("1.0", "end")
        self._welcome_process()

        self.txt_process.insert("end", "\n" + "─" * 60 + "\n", "title")
        self.txt_process.insert("end", "РАЗБОР СКРИПТА\n\n", "title")

        script = self.txt_input.get("1.0", "end")
        step = 0
        for raw in script.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            step += 1
            self.txt_process.insert("end", f"{step}. ", "step")
            self.txt_process.insert("end", f"{line}\n", "what")

        self.txt_process.insert("end", "\n" + "─" * 60 + "\n", "title")
        self.txt_process.insert("end", "ИТОГОВОЕ СОСТОЯНИЕ\n\n", "title")
        try:
            state = self.qi._get_statevector()
            probs = np.abs(np.asarray(state)) ** 2
            nonzero = int(np.sum(probs > 1e-6))
            self.txt_process.insert(
                "end",
                f"  Кубитов: {self.qi.config.num_qubits}\n"
                f"  Ненулевых амплитуд: {nonzero}\n"
                f"  Запутанных пар: {len(self.qi.entropy_history)}\n"
                f"  Измерений: {sum(len(v) for v in self.qi.measurement_history.values())}\n"
                f"  Ненулевых ячеек матрицы: {int(np.sum(self.qi.matrix != 0))}\n"
                f"  Папка запуска: {self.qi.run_dir}\n",
                "effect"
            )
            if self.qi.entropy_history:
                self.txt_process.insert("end", "\n  Энтропия запутанности:\n",
                                        "step")
                for lbl, s in self.qi.entropy_history:
                    self.txt_process.insert(
                        "end",
                        f"    {lbl}: S = {s:.3f} бит\n",
                        "effect"
                    )
        except Exception as e:
            self.txt_process.insert("end", f"  Ошибка: {e}\n", "what")

    # ---------------------------------------------------------- графики

    def refresh_plots(self):
        for ax in self.axes:
            ax.clear()

        try:
            state = self.qi._get_statevector()
            x, y, z = _bloch_coords(state, 0)
            norm = np.sqrt(x**2 + y**2 + z**2)
            if norm < 1e-6:
                _draw_bloch_mixed(self.axes[0], title="Блох q0")
            else:
                _draw_bloch_2d(self.axes[0], x, y, z, title="Блох q0")
        except Exception as e:
            self.axes[0].set_title(f"Блох: {e}")

        if self.qi.entropy_history:
            labels = [lbl for lbl, _ in self.qi.entropy_history]
            values = [v for _, v in self.qi.entropy_history]
            self.axes[1].bar(range(len(values)), values, color="purple",
                             alpha=0.75)
            self.axes[1].set_xticks(range(len(values)))
            self.axes[1].set_xticklabels(labels, rotation=45, ha="right",
                                         fontsize=7)
            self.axes[1].set_ylabel("S (бит)")
            self.axes[1].set_title("Энтропия запутанности")
            self.axes[1].axhline(1.0, color="red", linestyle="--", alpha=0.5)
            self.axes[1].set_ylim(0, 1.1)
        else:
            self.axes[1].set_title("Энтропия: нет данных")

        try:
            state = self.qi._get_statevector()
            probs = np.abs(np.asarray(state)) ** 2
            n = len(probs)
            labels = [format(i, f"0{self.qi.config.num_qubits}b")
                      for i in range(n)]
            bars = self.axes[2].bar(range(n), probs, color="teal", alpha=0.85)
            for bar, p in zip(bars, probs):
                if p > 0.01:
                    self.axes[2].text(bar.get_x() + bar.get_width() / 2,
                                      p + 0.01, f"{p:.2f}",
                                      ha="center", fontsize=7)
            self.axes[2].set_xticks(range(n))
            self.axes[2].set_xticklabels(labels, rotation=90, fontsize=6)
            self.axes[2].set_title("Амплитуды |i⟩")
            self.axes[2].set_ylabel("P")
            self.axes[2].set_ylim(0, 1.1)
        except Exception as e:
            self.axes[2].set_title(f"Амплитуды: {e}")

        try:
            m = self.qi.matrix
            nonzero = np.argwhere(m != 0)
            if len(nonzero) > 0:
                x_min, y_min = np.maximum(nonzero.min(axis=0) - 20, 0)
                x_max, y_max = np.minimum(nonzero.max(axis=0) + 20, m.shape)
            else:
                x_min, y_min = 0, 0
                x_max, y_max = 100, 100
            sub = m[x_min:x_max, y_min:y_max]
            self.axes[3].imshow(sub, cmap="viridis",
                                interpolation="nearest",
                                extent=[y_min, y_max, x_max, x_min])
            for name, pos in self.qi.portals.items():
                if pos:
                    py, px = pos[1], pos[0]
                    self.axes[3].plot(
                        py, px,
                        "ro" if name == "c1" else "wo",
                        markersize=10, markeredgecolor="black",
                    )
                    self.axes[3].text(py, px, name, color="white",
                                      fontsize=9, ha="center")
            self.axes[3].plot(self.qi.cursor[1], self.qi.cursor[0], "yx",
                              markersize=12, markeredgewidth=2)
            self.axes[3].set_title("Матрица пространства")
        except Exception as e:
            self.axes[3].set_title(f"Матрица: {e}")

        self.fig.tight_layout()
        self.canvas.draw()

    def _zoom(self, factor: float):
        for ax in self.axes:
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()
            cx = (xlim[0] + xlim[1]) / 2
            cy = (ylim[0] + ylim[1]) / 2
            ax.set_xlim(cx + (xlim[0] - cx) / factor,
                        cx + (xlim[1] - cx) / factor)
            ax.set_ylim(cy + (ylim[0] - cy) / factor,
                        cy + (ylim[1] - cy) / factor)
        self.canvas.draw()

    def _reset_zoom(self):
        for ax in self.axes:
            ax.autoscale()
        self.canvas.draw()

    def export_plots(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
        )
        if path:
            self.fig.savefig(path, dpi=150, bbox_inches="tight")
            self.status_msg.set(f"Графики → {path}")

    def _set_theme(self, theme: str):
        self.theme = theme
        if theme == "dark":
            bg = "#1e1e1e"
            fg = "#e0e0e0"
            self.root.configure(bg=bg)
            for w in (self.txt_input, self.txt_output, self.txt_process):
                w.configure(bg="#2b2b2b", fg=fg, insertbackground=fg)
            self.fig.patch.set_facecolor("#1e1e1e")
            for ax in self.axes:
                ax.set_facecolor("#2b2b2b")
                ax.tick_params(colors=fg)
                ax.title.set_color(fg)
                ax.xaxis.label.set_color(fg)
                ax.yaxis.label.set_color(fg)
        else:
            self.root.configure(bg="#f0f0f0")
            for w in (self.txt_input, self.txt_output, self.txt_process):
                w.configure(bg="white", fg="black", insertbackground="black")
            self.fig.patch.set_facecolor("white")
            for ax in self.axes:
                ax.set_facecolor("white")
                ax.tick_params(colors="black")
                ax.title.set_color("black")
                ax.xaxis.label.set_color("black")
                ax.yaxis.label.set_color("black")
        self.canvas.draw()
        self.status_msg.set(f"Тема: {theme}")

    def save_state(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if path:
            try:
                self.qi.save_state(path)
                self.txt_output.insert("end", f"\nСостояние → {path}\n")
                self.status_msg.set(f"Состояние → {path}")
            except Exception as e:
                messagebox.showerror("Ошибка",
                                     f"Не удалось сохранить: {e}")

    def load_state(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")],
        )
        if path:
            try:
                self.qi.load_state(path)
                self.var_num_qubits.set(self.qi.config.num_qubits)
                self.var_matrix_size.set(self.qi.config.matrix_size)
                self.var_rot_key.set(self.qi.config.rot_key)
                self.var_cursor_x.set(self.qi.config.cursor_start[0])
                self.var_cursor_y.set(self.qi.config.cursor_start[1])
                self.var_shots.set(self.qi.config.shots)
                self.txt_output.insert("end", f"\nСостояние ← {path}\n")
                self.refresh_plots()
                self.status_msg.set(f"Состояние ← {path}")
            except Exception as e:
                messagebox.showerror("Ошибка",
                                     f"Не удалось загрузить: {e}")

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("Справка по командам")
        win.geometry("720x680")

        text = tk.Text(win, font=("Consolas", 10), wrap="word")
        text.pack(fill="both", expand=True, padx=8, pady=8)

        help_content = """Классические команды:
  flp12 "текст"       ROT-преобразование
  set_portal c1       активировать портал c1
  set_portal h0       активировать портал h0
  go                  телепортация к h0 (запись 42)
  devixs              сброс матрицы
  move dx dy          сдвинуть курсор
  set_cell val        записать в матрицу

Переменные и конфиг:
  set VAR value       задать переменную ($VAR в командах)
  unset VAR           удалить
  vars                показать переменные
  config              показать конфиг
  config key value    изменить параметр

Квантовые:
  h q                 H-гейт
  x|y|z q             Pauli
  rx|ry|rz q θ        повороты (θ в радианах)
  cx|cz|swap a b      двухкубитные гейты
  measure_qubit q     измерение
  set_portal_q n q    портал → кубит
  entangle_portals a b  H+CNOT
  bloch q             сфера Блоха (со стрелками XY и Z)
  summary             СВОДНЫЙ PNG 3×3 (нумеруется: summary_1.png, ...)
  print_state         statevector
  qasm                QASM схемы

Файлы (всё в runs/<timestamp>/):
  save                сохранить состояние
  save_qasm           сохранить QASM
  save_report         сохранить отчёт

Папки запусков:
  new_run [prefix]    создать новую папку runs/<prefix>_<timestamp>/

Важно:
  summary НЕ создаётся автоматически. Вызывайте его вручную,
  когда хотите зафиксировать состояние.

Демо:
  Кнопка «Загрузить демо» или меню «Файл → Загрузить демо-скрипт»
  Кнопка «Сводный график» — единый PNG 3×3 (нумеруется)
"""
        text.insert("1.0", help_content)
        text.configure(state="disabled")


# ============================================================
#  Точка входа
# ============================================================

def run_gui():
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    QuantumGUI(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nGUI закрыт.")
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    run_gui()