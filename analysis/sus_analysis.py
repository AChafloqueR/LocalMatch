"""Análisis del Avance 3: descriptivo + normalidad + homogeneidad + prueba de comparación.

Uso:  python analysis/sus_analysis.py sus_respuestas.csv
"""
import sys

import pandas as pd
from scipy import stats

df = pd.read_csv(sys.argv[1] if len(sys.argv) > 1 else "sus_respuestas.csv")
a = df[df.perfil == "Personal de reclutamiento"].puntaje_sus
b = df[df.perfil == "Jefes de área"].puntaje_sus

print("\n== Descriptivo ==")
print(df.groupby("perfil").puntaje_sus.agg(["count", "mean", "std", "min", "max"]).round(1))
print("Total:", len(df), round(df.puntaje_sus.mean(), 1), round(df.puntaje_sus.std(), 1))
print(df.groupby(["perfil", "categoria"]).size().unstack(fill_value=0))

print("\n== Normalidad (Shapiro-Wilk) ==")
pa, pb = stats.shapiro(a).pvalue, stats.shapiro(b).pvalue
print(f"Reclutamiento p = {pa:.3f} | Jefes de área p = {pb:.3f}")

print("\n== Homogeneidad (Levene) ==")
lev = stats.levene(a, b)
print(f"F = {lev.statistic:.2f}, p = {lev.pvalue:.3f}")

print("\n== Comparación ==")
if pa > .05 and pb > .05:
    equal = lev.pvalue >= .05
    t = stats.ttest_ind(a, b, equal_var=equal)
    name = "t de Student" if equal else "t de Welch"
    df_t = len(a) + len(b) - 2 if equal else t.df
    print(f"{name}: t({df_t:.0f}) = {t.statistic:.2f}, p = {t.pvalue:.4f}; diferencia de medias = {a.mean() - b.mean():.1f}")
else:
    u = stats.mannwhitneyu(a, b, alternative="two-sided")
    print(f"U de Mann-Whitney: U = {u.statistic:.1f}, p = {u.pvalue:.4f}")
print("Decisión: se rechaza H0" if (t.pvalue if pa > .05 and pb > .05 else u.pvalue) < .05 else "Decisión: no se rechaza H0")
