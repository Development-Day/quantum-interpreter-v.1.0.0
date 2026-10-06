"""
QuantumInterpreter — гибридный классическо-квантовый интерпретатор.

Возможности:
  • Классический слой: порталы, ROT-текст, телепортация, матрица.
  • Квантовый слой (Qiskit): H, X, Y, Z, RX, RY, RZ, CX, CZ, SWAP,
    измерение, запутанность, statevector, энтропия фон Неймана.
  • Пользовательские переменные: set VAR value → $VAR в командах.
  • Визуализация: Блох (2D со стрелками XY и Z), матрица, гистограмма,
    энтропия, амплитуды, а также СВОДНЫЙ PNG 3×3 со всеми ключевыми графиками.
  • Сводный PNG нумеруется (summary_1.png, summary_2.png, …) — не перезаписывается.
  • Интерактивный REPL, режим скрипта, GUI на Tkinter.
  • Сохранение/загрузка состояния в JSON, экспорт схемы в QASM.
  • КАЖДЫЙ ЗАПУСК — В ОТДЕЛЬНОЙ ПАПКЕ runs/run_<timestamp>/

Поддерживаемые команды:
  --- классические (две формы) ---
    flp12"<text>" / flp12 "<text>"    ROT-преобразование
    ^<:c1 / ^<:h0 / set_portal <n>    активировать портал
    ?c1==1                            проверить калибровку портала c1
    go ^, it / go                     телепортация к h0
    devixs detected / devixs          обнулить матрицу
    move <dx> <dy>                    сдвинуть курсор
    set_cell <val>                    записать значение в матрицу

  --- переменные и параметры ---
    set <VAR> <value>          задать переменную
    unset <VAR>                удалить переменную
    vars                       показать все переменные
    config                     показать конфигурацию
    config <key> <value>       изменить параметр

  --- квантовые ---
    h <q>                      H-гейт
    x|y|z <q>                  Pauli-гейты
    rx|ry|rz <q> <θ>           повороты
    cx|cz|swap <a> <b>         двухкубитные гейты
    measure_qubit <q>          измерить кубит
    set_portal_q <name> <q>    привязать портал к кубиту
    entangle_portals <p1> <p2> H + CNOT
    bloch <q>                  сфера Блоха (нумеруется)
    print_state                statevector
    qasm                       QASM схемы
    summary                    сводный PNG 3×3 (нумеруется)

  --- файлы ---
    save                       сохранить состояние в папку запуска
    save_qasm                  экспорт QASM в папку запуска
    save_report                экспорт отчёта в папку запуска

  --- специальные ---
    :report                    отчёт
    :viz                       все визуализации (кроме summary)
    help                       справка
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import requests

from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import (
    Statevector,
    partial_trace,
    entropy,
    SparsePauliOp,
)
from qiskit_aer import AerSimulator

# --- Совместимость с Qiskit 1.x: .qasm() удалён ---
try:
    from qiskit import qasm2
    def _circuit_to_qasm(circuit):
        return qasm2.dumps(circuit)
except ImportError:
    def _circuit_to_qasm(circuit):
        return circuit.qasm()


# ============================================================
#  Управление папками запусков
# ============================================================

RUNS_ROOT = Path("runs")


def create_run_dir(prefix: str = "run") -> Path:
    """Создаёт новую папку runs/<prefix>_<YYYY-MM-DD_HH-MM-SS>/."""
    RUNS_ROOT.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = RUNS_ROOT / f"{prefix}_{ts}"
    run_dir.mkdir(exist_ok=True)
    return run_dir


# ============================================================
#  Конфигурация
# ============================================================

@dataclass
class Config:
    num_qubits: int = 4
    matrix_size: int = 1000
    cursor_start: tuple[int, int] = (6, 36)
    rot_key: int = 12
    shots: int = 1
    default_entropy_threshold_full: float = 0.99
    default_entropy_threshold_partial: float = 0.01

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["cursor_start"] = list(self.cursor_start)
        return d


# ============================================================
#  Улучшенная отрисовка Блоха
# ============================================================

def _draw_bloch_2d(ax, x: float, y: float, z: float, title: str = "") -> None:
    """
    Улучшенная 2D-визуализация сферы Блоха со стрелками XY и Z.
    """
    theta = np.linspace(0, 2 * np.pi, 200)
    ax.plot(np.cos(theta), np.sin(theta), color="black", lw=1.2)
    ax.plot(0.5 * np.cos(theta), 0.5 * np.sin(theta),
            color="gray", lw=0.8, linestyle="--", alpha=0.7)
    ax.axhline(0, color="gray", lw=0.5, alpha=0.6)
    ax.axvline(0, color="gray", lw=0.5, alpha=0.6)

    if abs(x) > 1e-6 or abs(y) > 1e-6:
        ax.quiver(0, 0, x, y,
                  angles="xy", scale_units="xy", scale=1,
                  color="red", width=0.03,
                  headwidth=4, headlength=5)

    if abs(z) > 1e-6:
        ax.arrow(0, 0, 0, z * 0.9,
                 head_width=0.06, head_length=0.08,
                 fc="blue", ec="blue", alpha=0.85,
                 length_includes_head=True)
        ax.text(0.06, z * 0.9 + 0.05 * np.sign(z),
                f"z={z:+.2f}", color="blue",
                fontsize=8, ha="left", va="center")

    ax.plot([x], [y], "o", color="orange",
            markersize=10, markeredgecolor="darkorange",
            markeredgewidth=1.5)

    ax.text(0.05, 0.05,
            f"x={x:+.2f}\ny={y:+.2f}",
            fontsize=8, va="bottom", ha="left",
            color="darkred",
            bbox=dict(boxstyle="round,pad=0.25",
                      facecolor="white", edgecolor="red", alpha=0.75))

    norm = float(np.sqrt(x**2 + y**2 + z**2))
    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.35, 1.35)
    ax.set_aspect("equal")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_title(f"{title}\n|v| = {norm:.3f}", fontsize=10)


def _draw_bloch_mixed(ax, title: str = "") -> None:
    """Отрисовка смешанного состояния (запутанный кубит)."""
    theta = np.linspace(0, 2 * np.pi, 200)
    ax.plot(np.cos(theta), np.sin(theta), color="black", lw=1.2)
    ax.plot(0.5 * np.cos(theta), 0.5 * np.sin(theta),
            color="gray", lw=0.8, linestyle="--", alpha=0.7)
    ax.axhline(0, color="gray", lw=0.5, alpha=0.6)
    ax.axvline(0, color="gray", lw=0.5, alpha=0.6)
    ax.plot(0, 0, "o", color="red", markersize=14,
            markeredgecolor="darkred", markeredgewidth=2)
    ax.text(0, -0.35,
            "СМЕШАННОЕ\n(запутан)",
            ha="center", va="top",
            fontsize=9, color="darkred",
            bbox=dict(boxstyle="round,pad=0.3",
                      facecolor="#ffe6e6",
                      edgecolor="red"))
    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.35, 1.35)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=10)


def _bloch_coords(state: Statevector, q: int) -> tuple[float, float, float]:
    rho = partial_trace(state, [i for i in range(state.num_qubits) if i != q])
    x = float(np.real(rho.expectation_value(SparsePauliOp("X"))))
    y = float(np.real(rho.expectation_value(SparsePauliOp("Y"))))
    z = float(np.real(rho.expectation_value(SparsePauliOp("Z"))))
    return x, y, z


# ============================================================
#  Основной класс
# ============================================================

class QuantumInterpreter:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()

        # Классическое состояние
        self.matrix = np.zeros(
            (self.config.matrix_size, self.config.matrix_size), dtype=int
        )
        self.cursor = list(self.config.cursor_start)
        self.portals: dict[str, tuple[int, int] | None] = {"c1": None, "h0": None}
        self.output: list[str] = []
        self.quantum_log: list[str] = []
        self.history: list[tuple] = []

        # Пользовательские переменные
        self.variables: dict[str, Any] = {}

        # Квантовое состояние
        self.circuit = QuantumCircuit(self.config.num_qubits, name="main")
        self.q_portals: dict[str, int] = {}
        self.measurement_history: dict[int, list[int]] = {
            i: [] for i in range(self.config.num_qubits)
        }
        self.entropy_history: list[tuple[str, float]] = []
        self.entropy_by_step: list[tuple[int, float]] = []  # эволюция энтропии

        # Счётчики
        self.bloch_counter: dict[int, int] = {
            i: 0 for i in range(self.config.num_qubits)
        }
        self.summary_counter: int = 0

        # Папка текущего запуска
        self.run_dir: Path = create_run_dir("run")
        self.output.append(f"Папка запуска: {self.run_dir}")

        self.state_sim = AerSimulator(method="statevector")
        self.qasm_sim = AerSimulator()

    # ---------------------------------------------------------- пути

    def _path(self, name: str) -> str:
        return str(self.run_dir / name)

    def new_run_dir(self, prefix: str = "run") -> Path:
        self.run_dir = create_run_dir(prefix)
        self.bloch_counter = {i: 0 for i in range(self.config.num_qubits)}
        self.summary_counter = 0
        self.output.append(f"Новая папка запуска: {self.run_dir}")
        return self.run_dir

    # ---------------------------------------------------------- logging

    def log_event(self, event: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")
        self.quantum_log.append(f"{ts} | {event}")

    # ------------------------------------------------ переменные

    def _substitute_vars(self, line: str) -> str:
        def repl(m):
            name = m.group(1) or m.group(2)
            if name not in self.variables:
                raise ValueError(f"Переменная '{name}' не определена")
            return str(self.variables[name])
        return re.sub(r"\$(\w+)|\$\{(\w+)\}", repl, line)

    def set_var(self, name: str, value: str) -> None:
        try:
            if "." in value:
                parsed: Any = float(value)
            else:
                parsed = int(value)
        except ValueError:
            parsed = value
        self.variables[name] = parsed
        self.output.append(f"$ {name} = {parsed!r}")

    def unset_var(self, name: str) -> None:
        if name in self.variables:
            del self.variables[name]
            self.output.append(f"$ {name} удалена")
        else:
            self.output.append(f"$ {name} не существует")

    def show_vars(self) -> None:
        if not self.variables:
            self.output.append("(переменных нет)")
            return
        for k, v in self.variables.items():
            self.output.append(f"  {k} = {v!r}")

    # ------------------------------------------------ config

    def show_config(self) -> None:
        for k, v in self.config.to_dict().items():
            self.output.append(f"  {k} = {v!r}")

    def set_config(self, key: str, value: str) -> None:
        if not hasattr(self.config, key):
            self.output.append(f"Неизвестный параметр: {key}")
            return
        cur = getattr(self.config, key)
        try:
            if isinstance(cur, bool):
                parsed: Any = value.lower() in ("1", "true", "yes")
            elif isinstance(cur, int):
                parsed = int(value)
            elif isinstance(cur, float):
                parsed = float(value)
            elif isinstance(cur, tuple):
                parts = value.split(",")
                parsed = tuple(int(p) for p in parts)
            else:
                parsed = value
        except ValueError as e:
            self.output.append(f"Ошибка парсинга '{value}': {e}")
            return
        setattr(self.config, key, parsed)
        self.output.append(f"config {key} = {parsed!r}")

        if key == "num_qubits":
            self._rebuild_quantum()
        elif key == "matrix_size":
            new_size = self.config.matrix_size
            self.matrix = np.zeros((new_size, new_size), dtype=int)
            self.cursor = list(self.config.cursor_start)
        elif key == "cursor_start":
            self.cursor = list(parsed)
            self.output.append(f"Курсор сброшен в {self.cursor}")

    def _rebuild_quantum(self) -> None:
        n = self.config.num_qubits
        self.circuit = QuantumCircuit(n, name="main")
        self.measurement_history = {i: [] for i in range(n)}
        self.q_portals.clear()
        self.entropy_history.clear()
        self.entropy_by_step.clear()
        self.bloch_counter = {i: 0 for i in range(n)}
        self.summary_counter = 0
        self.output.append(f"Квантовая схема пересоздана на {n} кубитов")

    # ------------------------------------------------ классические команды

    def set_portal(self, name: str) -> None:
        if name not in self.portals:
            self.portals[name] = None
        x, y = self.cursor
        self.portals[name] = (x, y)
        self.log_event(f"Портал {name} на ({x}, {y})")
        self.output.append(f"Портал '{name}' → ({x}, {y})")

    def flip_text(self, text: str, key: int) -> str:
        transformed = "".join(chr((ord(c) + key) % 0x110000) for c in text)
        self.log_event(f"ROT-{key}: '{text}' → '{transformed}'")
        return transformed

    def _move(self, dx: int, dy: int) -> None:
        x, y = self.cursor
        nx = max(0, min(self.matrix.shape[0] - 1, x + dx))
        ny = max(0, min(self.matrix.shape[1] - 1, y + dy))
        self.cursor = [nx, ny]
        self.output.append(f"Курсор → ({nx}, {ny})")

    def _set_cell(self, value: int) -> None:
        x, y = self.cursor
        self.matrix[x, y] = value
        self.output.append(f"Ячейка ({x}, {y}) = {value}")

    # ------------------------------------------------ квантовые операции

    def _check_qubit(self, qubit: int) -> None:
        if not (0 <= qubit < self.config.num_qubits):
            raise ValueError(
                f"Недопустимый кубит {qubit}. Всего: {self.config.num_qubits}"
            )

    def _get_statevector(self) -> Statevector:
        circ = self.circuit.copy()
        circ.save_statevector()
        circ = transpile(circ, self.state_sim)
        result = self.state_sim.run(circ).result()
        return Statevector(result.get_statevector())

    def apply_hadamard(self, qubit: int) -> None:
        self._check_qubit(qubit)
        self.circuit.h(qubit)
        self.output.append(f"H → q{qubit}")
        self.log_event(f"h q{qubit}")

    def apply_pauli(self, gate: str, qubit: int) -> None:
        self._check_qubit(qubit)
        getattr(self.circuit, gate)(qubit)
        self.output.append(f"{gate.upper()} → q{qubit}")

    def apply_rotation(self, gate: str, qubit: int, theta: float) -> None:
        self._check_qubit(qubit)
        getattr(self.circuit, gate)(theta, qubit)
        self.output.append(f"{gate.upper()}({theta:.3f}) → q{qubit}")

    def apply_two_qubit(self, gate: str, a: int, b: int) -> None:
        self._check_qubit(a)
        self._check_qubit(b)
        if a == b:
            raise ValueError("Кубиты должны быть разными")
        getattr(self.circuit, gate)(a, b)
        self.output.append(f"{gate.upper()} q{a} q{b}")

    def measure_qubit(self, qubit: int) -> int:
        self._check_qubit(qubit)
        meas_circ = QuantumCircuit(self.config.num_qubits, self.config.num_qubits)
        meas_circ.compose(self.circuit, inplace=True)
        meas_circ.measure(qubit, qubit)
        meas_circ = transpile(meas_circ, self.qasm_sim)
        result = self.qasm_sim.run(
            meas_circ, shots=self.config.shots, memory=True
        ).result()
        raw = result.get_memory()[0]
        bit = int(raw[::-1][qubit])

        self.measurement_history[qubit].append(bit)
        self.circuit.reset(qubit)
        if bit == 1:
            self.circuit.x(qubit)

        self.output.append(f"Измерение q{qubit} → |{bit}>")
        return bit

    def set_portal_q(self, name: str, qubit: int) -> None:
        self._check_qubit(qubit)
        self.q_portals[name] = qubit
        self.output.append(f"Портал '{name}' → q{qubit}")

    def entangle_portals(self, p1: str, p2: str) -> Statevector | None:
        if p1 not in self.q_portals or p2 not in self.q_portals:
            self.output.append(f"Ошибка: порталы '{p1}' и/или '{p2}' не заданы")
            return None
        q1, q2 = self.q_portals[p1], self.q_portals[p2]
        if q1 == q2:
            self.output.append("Ошибка: один и тот же кубит")
            return None

        self.circuit.reset(q1)
        self.circuit.reset(q2)
        self.circuit.h(q1)
        self.circuit.cx(q1, q2)

        state = self._get_statevector()
        s_val = self._entanglement_entropy(state, q1)
        level = self._entanglement_level(state, q1)
        self.entropy_history.append((f"{p1}↔{p2}", s_val))
        self.entropy_by_step.append((len(self.entropy_history), s_val))
        self.output.append(f"Запутаны '{p1}' (q{q1}) и '{p2}' (q{q2}). {level}")
        self._visualize_entanglement(state, q1, q2)
        return state

    def _entanglement_entropy(self, state: Statevector, q: int) -> float:
        rho = partial_trace(state, [i for i in range(state.num_qubits) if i != q])
        return float(entropy(rho, base=2))

    def _entanglement_level(self, state: Statevector, q: int) -> str:
        s = self._entanglement_entropy(state, q)
        if s > self.config.default_entropy_threshold_full:
            return f"Полная запутанность (S={s:.3f})"
        if s > self.config.default_entropy_threshold_partial:
            return f"Частичная запутанность (S={s:.3f})"
        return f"Нет запутанности (S={s:.3f})"

    # ------------------------------------------------ визуализация

    def visualize_qubit(self, qubit: int, filename: str | None = None) -> str:
        self._check_qubit(qubit)
        state = self._get_statevector()
        x, y, z = _bloch_coords(state, qubit)
        norm = np.sqrt(x**2 + y**2 + z**2)

        fig, ax = plt.subplots(figsize=(5, 5))
        if norm < 1e-6:
            _draw_bloch_mixed(ax, title=f"Кубит {qubit}")
        else:
            _draw_bloch_2d(ax, x, y, z, title=f"Кубит {qubit}")

        if filename is None:
            self.bloch_counter[qubit] += 1
            idx = self.bloch_counter[qubit]
            fname = self._path(f"qubit_{qubit}_bloch_{idx}.png")
        else:
            fname = self._path(filename) if not os.path.isabs(filename) else filename

        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        self.output.append(f"Блох q{qubit} → {fname}")
        return fname

    def _visualize_entanglement(self, state, q1, q2) -> None:
        fig, axes = plt.subplots(1, 2, figsize=(12, 6))
        for ax, q in zip(axes, [q1, q2]):
            x, y, z = _bloch_coords(state, q)
            norm = np.sqrt(x**2 + y**2 + z**2)
            if norm < 1e-6:
                _draw_bloch_mixed(ax, title=f"Кубит {q}")
            else:
                _draw_bloch_2d(ax, x, y, z, title=f"Кубит {q}")
        fig.suptitle("Запутанность порталов")
        fig.tight_layout()
        fname = self._path("entanglement.png")
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        self.output.append(f"Запутанность → {fname}")

    def visualize(self, filename: str = "quantum_space.png") -> str:
        fig, ax = plt.subplots(figsize=(10, 8))
        colors = ["black", "purple", "blue", "cyan", "green", "yellow", "red"]
        cmap = LinearSegmentedColormap.from_list("quantum", colors)
        nonzero = np.argwhere(self.matrix != 0)
        if len(nonzero) > 0:
            x_min, y_min = np.maximum(nonzero.min(axis=0) - 20, 0)
            x_max, y_max = np.minimum(nonzero.max(axis=0) + 20,
                                      self.matrix.shape)
        else:
            x_min, y_min = 0, 0
            x_max, y_max = 100, 100
        sub = self.matrix[x_min:x_max, y_min:y_max]
        ax.imshow(sub, cmap=cmap, interpolation="nearest",
                  extent=[y_min, y_max, x_max, x_min])
        for name, pos in self.portals.items():
            if pos:
                py, px = pos[1], pos[0]
                ax.plot(py, px, "ro" if name == "c1" else "wo",
                        markersize=12, markeredgecolor="black")
                ax.text(py, px, name, color="white", fontsize=12, ha="center")
        ax.plot(self.cursor[1], self.cursor[0], "yx",
                markersize=15, markeredgewidth=2, label="cursor")
        ax.set_title("Квантовое пространство")
        ax.set_xlabel("Y")
        ax.set_ylabel("X")
        fig.colorbar(plt.cm.ScalarMappable(cmap=cmap), ax=ax,
                     label="Энергия")
        fig.tight_layout()
        fname = self._path(filename)
        fig.savefig(fname)
        plt.close(fig)
        self.output.append(f"Пространство → {fname}")
        return fname

    def plot_measurement_history(self, filename="measurements.png") -> str:
        if not any(self.measurement_history.values()):
            self.output.append("Нет измерений")
            return ""
        fig, ax = plt.subplots(figsize=(8, 4))
        for q, bits in self.measurement_history.items():
            if bits:
                ax.hist([q] * len(bits),
                        bins=np.arange(-0.5, self.config.num_qubits + 0.5, 1),
                        weights=[1 if b else -1 for b in bits],
                        alpha=0.6, label=f"q{q} (n={len(bits)})")
        ax.set_xlabel("Кубит")
        ax.set_ylabel("Сумма")
        ax.set_title("История измерений")
        ax.legend()
        fname = self._path(filename)
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        self.output.append(f"Измерения → {fname}")
        return fname

    def plot_entropy_history(self, filename="entropy.png") -> str:
        if not self.entropy_history:
            self.output.append("Нет энтропии")
            return ""
        labels = [lbl for lbl, _ in self.entropy_history]
        values = [v for _, v in self.entropy_history]
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(range(len(values)), values, color="purple", alpha=0.7)
        ax.set_xticks(range(len(values)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_ylabel("S (бит)")
        ax.set_title("Энтропия запутанности")
        ax.axhline(1.0, color="red", linestyle="--", alpha=0.5, label="макс S=1")
        ax.legend()
        fig.tight_layout()
        fname = self._path(filename)
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        self.output.append(f"Энтропия → {fname}")
        return fname

    def plot_entropy_evolution(self, filename="entropy_evolution.png") -> str:
        """График эволюции энтропии по шагам."""
        if not self.entropy_by_step:
            self.output.append("Нет эволюции энтропии")
            return ""
        steps = [s for s, _ in self.entropy_by_step]
        values = [v for _, v in self.entropy_by_step]
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(steps, values, "o-", color="darkviolet",
                linewidth=2, markersize=8)
        for s, v in zip(steps, values):
            ax.annotate(f"{v:.3f}", (s, v),
                        textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=8)
        ax.set_xlabel("Шаг запутывания")
        ax.set_ylabel("S (бит)")
        ax.set_title("Эволюция энтропии запутанности")
        ax.axhline(1.0, color="red", linestyle="--", alpha=0.5,
                   label="макс S=1")
        ax.set_ylim(0, 1.1)
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fname = self._path(filename)
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        self.output.append(f"Эволюция энтропии → {fname}")
        return fname

    def plot_statevector_amplitudes(self, filename="amplitudes.png") -> str:
        state = self._get_statevector()
        probs = np.abs(np.asarray(state)) ** 2
        fig, ax = plt.subplots(figsize=(max(8, len(probs) * 0.4), 4))
        ax.bar(range(len(probs)), probs, color="teal", alpha=0.8)
        ax.set_xlabel("|i⟩")
        ax.set_ylabel("P")
        ax.set_title("Амплитуды statevector")
        fig.tight_layout()
        fname = self._path(filename)
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        self.output.append(f"Амплитуды → {fname}")
        return fname

    # ------------------------------------------------ СВОДНЫЙ PNG 3×3

    def summary_plot(self, filename: str | None = None) -> str:
        """
        Сводный PNG 3×3. Нумеруется: summary_1.png, summary_2.png, ...
        """
        self.summary_counter += 1
        if filename is None:
            filename = f"summary_{self.summary_counter}.png"
        elif not os.path.isabs(filename):
            filename = self._path(filename)

        fig, axes = plt.subplots(3, 3, figsize=(16, 14))
        fig.suptitle(
            f"QuantumInterpreter — Сводный отчёт #{self.summary_counter}\n{self.run_dir}",
            fontsize=14, fontweight="bold"
        )

        try:
            state = self._get_statevector()
        except Exception:
            state = None

        # 1-4. Блох
        for idx, q in enumerate(range(min(4, self.config.num_qubits))):
            ax = axes[idx // 3][idx % 3]
            try:
                if state is not None:
                    x, y, z = _bloch_coords(state, q)
                    norm = np.sqrt(x**2 + y**2 + z**2)
                    if norm < 1e-6:
                        _draw_bloch_mixed(ax, title=f"Блох q{q}")
                    else:
                        _draw_bloch_2d(ax, x, y, z, title=f"Блох q{q}")
                else:
                    ax.set_title(f"Блох q{q}: нет данных")
            except Exception as e:
                ax.set_title(f"Блох q{q}: {e}")

        # 5. Энтропия + эволюция
        ax = axes[1][1]
        if self.entropy_by_step:
            steps = [s for s, _ in self.entropy_by_step]
            values = [v for _, v in self.entropy_by_step]
            ax.plot(steps, values, "o-", color="darkviolet",
                    linewidth=2, markersize=8)
            for s, v in zip(steps, values):
                ax.annotate(f"{v:.2f}", (s, v),
                            textcoords="offset points",
                            xytext=(0, 8), ha="center", fontsize=7)
            ax.axhline(1.0, color="red", linestyle="--", alpha=0.5)
            ax.set_ylim(0, 1.1)
            ax.set_xlabel("Шаг")
            ax.set_ylabel("S (бит)")
            ax.set_title("Эволюция энтропии")
            ax.grid(True, alpha=0.3)
        elif self.entropy_history:
            labels = [lbl for lbl, _ in self.entropy_history]
            values = [v for _, v in self.entropy_history]
            ax.bar(range(len(values)), values, color="purple", alpha=0.75)
            ax.set_xticks(range(len(values)))
            ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
            ax.set_ylabel("S (бит)")
            ax.set_title("Энтропия запутанности")
            ax.axhline(1.0, color="red", linestyle="--", alpha=0.5)
            ax.set_ylim(0, 1.1)
        else:
            ax.set_title("Энтропия: нет данных")

        # 6. Амплитуды
        ax = axes[1][2]
        try:
            if state is not None:
                probs = np.abs(np.asarray(state)) ** 2
                n = len(probs)
                labels = [format(i, f"0{self.config.num_qubits}b")
                          for i in range(n)]
                bars = ax.bar(range(n), probs, color="teal", alpha=0.85)
                for bar, p in zip(bars, probs):
                    if p > 0.05:
                        ax.text(bar.get_x() + bar.get_width() / 2,
                                p + 0.01, f"{p:.2f}",
                                ha="center", fontsize=6)
                ax.set_xticks(range(n))
                ax.set_xticklabels(labels, rotation=90, fontsize=5)
                ax.set_title("Амплитуды statevector")
                ax.set_ylabel("P")
                ax.set_ylim(0, 1.1)
            else:
                ax.set_title("Амплитуды: нет данных")
        except Exception as e:
            ax.set_title(f"Амплитуды: {e}")

        # 7. Матрица
        ax = axes[2][0]
        try:
            m = self.matrix
            nonzero = np.argwhere(m != 0)
            if len(nonzero) > 0:
                x_min, y_min = np.maximum(nonzero.min(axis=0) - 20, 0)
                x_max, y_max = np.minimum(nonzero.max(axis=0) + 20, m.shape)
            else:
                x_min, y_min = 0, 0
                x_max, y_max = 100, 100
            sub = m[x_min:x_max, y_min:y_max]
            colors = ["black", "purple", "blue", "cyan",
                      "green", "yellow", "red"]
            cmap = LinearSegmentedColormap.from_list("quantum", colors)
            ax.imshow(sub, cmap=cmap, interpolation="nearest",
                      extent=[y_min, y_max, x_max, x_min])
            for name, pos in self.portals.items():
                if pos:
                    py, px = pos[1], pos[0]
                    ax.plot(py, px, "ro" if name == "c1" else "wo",
                            markersize=9, markeredgecolor="black")
                    ax.text(py, px, name, color="white",
                            fontsize=8, ha="center")
            ax.plot(self.cursor[1], self.cursor[0], "yx",
                    markersize=11, markeredgewidth=2)
            ax.set_title("Матрица пространства")
        except Exception as e:
            ax.set_title(f"Матрица: {e}")

        # 8. Измерения
        ax = axes[2][1]
        if any(self.measurement_history.values()):
            for q, bits in self.measurement_history.items():
                if bits:
                    zeros = bits.count(0)
                    ones = bits.count(1)
                    ax.bar([f"q{q}\n|0⟩", f"q{q}\n|1⟩"],
                           [zeros, ones], alpha=0.6,
                           label=f"q{q} (n={len(bits)})")
            ax.set_ylabel("Количество")
            ax.set_title("Измерения по кубитам")
            ax.legend(fontsize=7)
        else:
            ax.set_title("Измерения: нет данных")

        # 9. Текстовая сводка + QASM + statevector
        ax = axes[2][2]
        ax.axis("off")
        lines = [
            f"СВОДКА #{self.summary_counter}",
            "─" * 34,
            f"Кубитов: {self.config.num_qubits}",
            f"Матрица: {self.config.matrix_size}×{self.config.matrix_size}",
            f"ROT-ключ: {self.config.rot_key}  Shots: {self.config.shots}",
            "",
            "ПОРТАЛЫ (классич.):",
        ]
        for k, v in self.portals.items():
            lines.append(f"  {k}: {v}")
        lines.append("")
        lines.append("ПОРТАЛЫ (квантовые):")
        if self.q_portals:
            for k, v in self.q_portals.items():
                lines.append(f"  {k} → q{v}")
        else:
            lines.append("  (нет)")
        lines.append("")
        lines.append("ПЕРЕМЕННЫЕ:")
        if self.variables:
            for k, v in self.variables.items():
                lines.append(f"  {k} = {v!r}")
        else:
            lines.append("  (нет)")
        lines.append("")
        lines.append("ЭНТРОПИЯ:")
        for lbl, s in self.entropy_history:
            lines.append(f"  {lbl}: S={s:.3f}")
        lines.append("")
        lines.append(f"Ненулевых ячеек матрицы: "
                     f"{int(np.sum(self.matrix != 0))}")
        lines.append(f"Измерений: "
                     f"{sum(len(v) for v in self.measurement_history.values())}")

        # QASM (первые 8 строк)
        lines.append("")
        lines.append("QASM (первые строки):")
        try:
            qasm = _circuit_to_qasm(self.circuit)
            for ln in qasm.splitlines()[:8]:
                lines.append(f"  {ln}")
            if len(qasm.splitlines()) > 8:
                lines.append("  …")
        except Exception as e:
            lines.append(f"  ошибка: {e}")

        # Statevector (ненулевые)
        lines.append("")
        lines.append("STATEVECTOR (ненулевые):")
        try:
            if state is not None:
                probs = np.abs(np.asarray(state)) ** 2
                nz = np.where(probs > 1e-6)[0]
                for i in nz[:6]:
                    amp = np.asarray(state)[i]
                    lines.append(
                        f"  |{format(i, f'0{self.config.num_qubits}b')}⟩: "
                        f"{amp.real:+.2f}{amp.imag:+.2f}j  "
                        f"P={probs[i]:.2f}"
                    )
                if len(nz) > 6:
                    lines.append(f"  … ещё {len(nz) - 6}")
            else:
                lines.append("  (нет данных)")
        except Exception as e:
            lines.append(f"  ошибка: {e}")

        ax.text(0.02, 0.98, "\n".join(lines),
                transform=ax.transAxes,
                va="top", ha="left",
                family="monospace", fontsize=7,
                bbox=dict(boxstyle="round", facecolor="#f5f5f5",
                          edgecolor="#999"))

        fig.tight_layout(rect=[0, 0, 1, 0.97])
        fname = self._path(filename)
        fig.savefig(fname, dpi=120, bbox_inches="tight")
        plt.close(fig)
        self.output.append(f"Сводный график #{self.summary_counter} → {fname}")
        return fname

    def save_all_visualizations(self) -> None:
        """
        Сохраняет все PNG в папку запуска, КРОМЕ summary.png.
        Summary создаётся только явно командой summary.
        """
        self.visualize()
        self.plot_measurement_history()
        self.plot_entropy_history()
        self.plot_entropy_evolution()
        self.plot_statevector_amplitudes()

    # ------------------------------------------------ сеть

    def connect_to_quantum_web(self, timeout: float = 3.0) -> str:
        try:
            r = requests.get("https://api.quantumnetwork.io/metadata",
                             timeout=timeout)
            if r.status_code == 200:
                qt = r.json().get("quantum_time", "неизвестно")
                return f"✓ Quantum Web | {qt}"
            return f"✗ Код {r.status_code}"
        except requests.RequestException as e:
            return f"✗ Нет подключения: {e}"

    # ------------------------------------------------ сохранение/загрузка

    def save_state(self, path: str | None = None) -> str:
        if path is None:
            path = self._path("state.json")
        elif not os.path.isabs(path):
            path = self._path(path)

        data = {
            "run_dir": str(self.run_dir),
            "config": self.config.to_dict(),
            "matrix": self.matrix.tolist(),
            "cursor": self.cursor,
            "portals": {k: list(v) if v else None
                        for k, v in self.portals.items()},
            "q_portals": self.q_portals,
            "variables": self.variables,
            "measurement_history": self.measurement_history,
            "entropy_history": self.entropy_history,
            "qasm": _circuit_to_qasm(self.circuit),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.output.append(f"Состояние → {path}")
        return path

    def load_state(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cfg = Config(**{**data["config"],
                        "cursor_start": tuple(data["config"]["cursor_start"])})
        self.config = cfg
        self.matrix = np.array(data["matrix"], dtype=int)
        self.cursor = list(data["cursor"])
        self.portals = {k: tuple(v) if v else None
                        for k, v in data["portals"].items()}
        self.q_portals = data["q_portals"]
        self.variables = data["variables"]
        self.measurement_history = {int(k): v for k, v in
                                    data["measurement_history"].items()}
        self.entropy_history = [tuple(x) for x in data["entropy_history"]]

        self.circuit = QuantumCircuit.from_qasm_str(data["qasm"])
        self.state_sim = AerSimulator(method="statevector")
        self.qasm_sim = AerSimulator()
        self.output.append(f"Состояние ← {path}")

    def save_qasm(self, path: str | None = None) -> str:
        if path is None:
            path = self._path("circuit.qasm")
        elif not os.path.isabs(path):
            path = self._path(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_circuit_to_qasm(self.circuit))
        self.output.append(f"QASM → {path}")
        return path

    def save_report(self, path: str | None = None) -> str:
        if path is None:
            path = self._path("report.txt")
        elif not os.path.isabs(path):
            path = self._path(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.report())
        self.output.append(f"Отчёт → {path}")
        return path

    # ------------------------------------------------ execute

    def execute_line(self, line: str) -> None:
        line = line.strip()
        if not line or line.startswith("#"):
            return

        try:
            line = self._substitute_vars(line)
        except ValueError as e:
            self.output.append(f"Ошибка переменной: {e}")
            return

        self.log_event(f"Строка: {line}")

        # --- классические команды (оригинальный синтаксис) ---
        if 'flp12"' in line:
            handled = False
            for part in line.split('flp12"')[1:]:
                if '"' in part:
                    text = part.split('"')[0]
                    self.output.append(self.flip_text(text, self.config.rot_key))
                    handled = True
            if handled:
                return

        if "^<" in line:
            if ":c1" in line:
                self.set_portal("c1")
            if ":h0" in line:
                self.set_portal("h0")
            return

        if "?c1==1" in line:
            if self.portals["c1"] == (1, 1):
                self.output.append("Квантовое соответствие!")
            else:
                self.output.append(
                    f"Портал c1 не калиброван: {self.portals['c1']}"
                )
            return

        if "go ^, it" in line:
            target = self.portals.get("h0") or (0, 0)
            self.cursor = list(target)
            self.matrix[target] = 42
            self.history.append(("TELEPORT", tuple(target),
                                 self.matrix.copy()))
            self.output.append(f"Телепортация → {target}, записано 42")
            return

        if "devixs detected" in line:
            self.matrix = np.zeros_like(self.matrix)
            self.output.append("Матрица обнулена")
            self.history.append(("RESET", tuple(self.cursor),
                                 self.matrix.copy()))
            return

        # --- парсинг через split() ---
        parts = line.split()
        if not parts:
            return
        cmd, *args = parts

        try:
            if cmd == "set" and len(args) >= 2:
                self.set_var(args[0], " ".join(args[1:]))
            elif cmd == "unset":
                self.unset_var(args[0])
            elif cmd == "vars":
                self.show_vars()
            elif cmd == "config":
                if not args:
                    self.show_config()
                else:
                    self.set_config(args[0], " ".join(args[1:]))

            elif cmd == "flp12":
                rest = line[len("flp12"):].strip()
                text = rest.strip('"') if rest.startswith('"') else rest
                if text:
                    self.output.append(
                        self.flip_text(text, self.config.rot_key)
                    )
                else:
                    self.output.append("flp12: пустой текст")

            elif cmd == "set_portal":
                if args:
                    self.set_portal(args[0])
                else:
                    self.output.append(
                        "set_portal: укажите имя портала (c1 / h0)"
                    )

            elif cmd == "go":
                target = self.portals.get("h0") or (0, 0)
                self.cursor = list(target)
                self.matrix[target] = 42
                self.history.append(("TELEPORT", tuple(target),
                                     self.matrix.copy()))
                self.output.append(f"Телепортация → {target}, записано 42")

            elif cmd == "devixs":
                self.matrix = np.zeros_like(self.matrix)
                self.output.append("Матрица обнулена")
                self.history.append(("RESET", tuple(self.cursor),
                                     self.matrix.copy()))

            elif cmd == "move":
                self._move(int(args[0]), int(args[1]))
            elif cmd == "set_cell":
                self._set_cell(int(args[0]))

            elif cmd == "h":
                self.apply_hadamard(int(args[0]))
            elif cmd in ("x", "y", "z"):
                self.apply_pauli(cmd, int(args[0]))
            elif cmd in ("rx", "ry", "rz"):
                self.apply_rotation(cmd, int(args[0]), float(args[1]))
            elif cmd in ("cx", "cz", "swap"):
                self.apply_two_qubit(cmd, int(args[0]), int(args[1]))
            elif cmd == "measure_qubit":
                bit = self.measure_qubit(int(args[0]))
                if bit == 1:
                    x, y = self.cursor
                    self.matrix[x, y] = 99
            elif cmd == "set_portal_q":
                self.set_portal_q(args[0], int(args[1]))
            elif cmd == "entangle_portals":
                self.entangle_portals(args[0], args[1])
            elif cmd == "bloch":
                self.visualize_qubit(int(args[0]))
            elif cmd == "summary":
                self.summary_plot()
            elif cmd == "print_state":
                self.output.append(f"Statevector: {self._get_statevector()}")
            elif cmd == "qasm":
                self.output.append("QASM:\n" + _circuit_to_qasm(self.circuit))
            elif cmd == "save":
                if args:
                    self.save_state(args[0])
                else:
                    self.save_state()
            elif cmd == "load":
                self.load_state(args[0])
            elif cmd == "save_qasm":
                if args:
                    self.save_qasm(args[0])
                else:
                    self.save_qasm()
            elif cmd == "save_report":
                if args:
                    self.save_report(args[0])
                else:
                    self.save_report()
            elif cmd == "new_run":
                self.new_run_dir(args[0] if args else "run")
            elif cmd == "help":
                self.output.append(HELP_TEXT)
            else:
                self.output.append(f"Неизвестная команда: '{cmd}'")
        except (IndexError, ValueError) as e:
            self.output.append(f"Ошибка в '{line}': {e}")

    def execute(self, script: str) -> list[str]:
        self.cursor = list(self.config.cursor_start)
        for line in script.splitlines():
            self.execute_line(line)

        # Автосохранение в конце (БЕЗ summary — его пользователь вызывает сам)
        try:
            self.save_all_visualizations()
            self.save_state()
            self.save_qasm()
            self.save_report()
        except Exception as e:
            self.output.append(f"[автосохранение] ошибка: {e}")

        return self.output

    def report(self) -> str:
        lines = ["=" * 60, "КВАНТОВЫЙ ИНТЕРПРЕТАТОР :: ОТЧЁТ", "=" * 60]
        lines.append(f"\n[ПАПКА ЗАПУСКА] {self.run_dir}")
        lines.append("\n[ВЫВОД]")
        lines += [f"{i}. {o}" for i, o in enumerate(self.output, 1)]
        lines.append("\n[ПОРТАЛЫ]")
        lines += [f"{k}: {v}" for k, v in self.portals.items()]
        lines.append("\n[КВАНТОВЫЕ ПОРТАЛЫ]")
        lines += [f"{k} → q{v}" for k, v in self.q_portals.items()] or ["(нет)"]
        lines.append("\n[ПЕРЕМЕННЫЕ]")
        lines += [f"{k} = {v!r}" for k, v in self.variables.items()] or ["(нет)"]
        lines.append("\n[КОНФИГ]")
        lines += [f"{k} = {v!r}" for k, v in self.config.to_dict().items()]
        lines.append("\n[МАТРИЦА]")
        nz = np.argwhere(self.matrix != 0)
        lines.append(f"Ненулевых: {len(nz)}, макс: {np.max(self.matrix)}")
        lines.append("\n[ИЗМЕРЕНИЯ]")
        for q, bits in self.measurement_history.items():
            if bits:
                lines.append(f"q{q}: {bits}")
        lines.append("\n[ЭНТРОПИЯ]")
        for lbl, s in self.entropy_history:
            lines.append(f"{lbl}: S={s:.3f}")
        return "\n".join(lines)


HELP_TEXT = """
Команды:
  # переменные и конфиг
  set VAR value        задать переменную ($VAR в командах)
  unset VAR            удалить
  vars                 показать
  config               показать конфиг
  config key value     изменить параметр

  # классические
  flp12 "text"         ROT-преобразование
  set_portal c1        активировать портал c1
  set_portal h0        активировать портал h0
  go                   телепортация к h0
  devixs               сброс матрицы
  move dx dy           сдвинуть курсор
  set_cell val         записать в матрицу

  # квантовые
  h q                  H-гейт
  x|y|z q              Pauli
  rx|ry|rz q theta     повороты
  cx|cz|swap a b       двухкубитные
  measure_qubit q      измерение
  set_portal_q n q     портал → кубит
  entangle_portals a b H+CNOT
  bloch q              Блох (нумеруется)
  summary              сводный PNG 3×3 (нумеруется)
  print_state          statevector
  qasm                 QASM

  # файлы (всё в папке запуска)
  save                 сохранить состояние в state.json
  save_qasm            сохранить QASM в circuit.qasm
  save_report          сохранить отчёт в report.txt

  # папки запусков
  new_run [prefix]     создать новую папку runs/<prefix>_<timestamp>/

  # спец
  :report              отчёт
  :viz                 все PNG (кроме summary)
  help                 справка
"""


# ============================================================
#  REPL
# ============================================================

def run_repl(config: Config | None = None) -> None:
    qi = QuantumInterpreter(config)
    print("=" * 60)
    print("  QuantumInterpreter REPL  (help — справка, :quit — выход)")
    print(f"  Папка запуска: {qi.run_dir}")
    print("=" * 60)
    while True:
        try:
            line = input("q> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break
        if not line:
            continue
        if line in (":quit", ":exit", "quit", "exit"):
            break
        if line == ":report":
            print(qi.report())
            continue
        if line == ":viz":
            qi.save_all_visualizations()
            print(f"Все PNG сохранены в {qi.run_dir} (кроме summary)")
            continue
        if line == ":new_run":
            qi.new_run_dir()
            print(f"Новая папка запуска: {qi.run_dir}")
            continue
        qi.execute_line(line)
        for out in qi.output[-3:]:
            print(f"  → {out}")


# ============================================================
#  Демо-скрипт
# ============================================================

def run_example() -> None:
    qi = QuantumInterpreter(Config(num_qubits=4, matrix_size=500))
    script = """
    config num_qubits 4
    config matrix_size 500

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

    config cursor_start 200,200
    move 0 0
    set_portal c1
    config cursor_start 350,250
    move 0 0
    set_portal h0

    flp12 "hello quantum"

    h 0
    x 1
    y 2
    z 3

    bloch 0
    bloch 1
    bloch 2
    bloch 3

    set_portal_q alpha 0
    set_portal_q beta 1
    entangle_portals alpha beta

    # СВОДКА ДО ИЗМЕРЕНИЙ (богатая картина)
    summary

    measure_qubit 0
    print_state
    qasm
    """
    qi.execute(script)
    print(qi.report())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--repl":
        run_repl()
    elif len(sys.argv) > 1 and sys.argv[1] == "--gui":
        from gui import run_gui
        run_gui()
    else:
        run_example()