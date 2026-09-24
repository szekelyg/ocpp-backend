# app/services/negyedorak.py
"""Töltőnkénti negyedórás energia (Wh) – az energiaközösségi almérő-integrációhoz.

Az ek (app.energiafelho.hu) a töltőt egy mérési pont (POD) ALMÉRŐJEKÉNT mutatja
(TERV-elszamolas-2, D lépés). Az almérő NEM számol bele az elszámolásba, csak
megjelenítés – de a számnak attól még igaznak kell lennie, ezért itt a lehető
legpontosabb forrásból dolgozunk.

Honnan jön az energia (sessiononként, töltésenként):

1. **MeterValues-minták** (`meter_samples.energy_wh_total`, Energy.Active.Import.Register),
   amelyek a sessionhöz kötöttek (`session_id`). A session kumulált energiája a minták
   időpontjaiban ismert; a minták között (és a session eleje / első minta, utolsó minta /
   vége között) lineárisan interpolálunk. A negyedóra energiája = C(negyedóra vége) −
   C(negyedóra eleje). Módszer: `meter_values`.
2. Ha a sessionhöz **nincs energiaminta**, de le van zárva és van energiája
   (`energy_kwh`, a meterStart/meterStop-ból): a session energiáját **időarányosan**
   osztjuk el a session negyedóráira (egyenletes teljesítményt feltételezve). Ez közelítés
   – egy töltés eleje jellemzően erősebb, a vége (CV-szakasz) gyengébb –, ezért a sor
   `session_aranyositas` jelölést kap. Módszer: `session_aranyositas`.

Nincs adat → nincs sor (nem nulla): a session-ön kívüli negyedórákra nem adunk semmit.
A töltő ilyenkor jó eséllyel nem vett fel energiát, de ezt nem MÉRTÜK – az ek dönti el,
mit mutat. Egy session-ön belüli, ténylegesen 0 Wh-s negyedóra viszont 0 (mért adat).

A regiszter skálája töltőnként más (van, amelyik élettartam-számlálót küld, van,
amelyik session-relatívat; lásd `handlers/transactions.py` „mismatch fallback"). Ezért az
alapszintet (base) a mintákhoz igazítjuk: meterStart, ha a minták annak skáláján vannak;
0, ha a minták session-relatívak; különben az első minta (az első minta előtti energia
ekkor az első szakaszra nem jut, a session végi energia-többlet az utolsó szakaszra).
Ha a lezárt session hivatalos energiája (`energy_kwh`, ebből lett a számla) kisebb,
mint amit a minták mutatnak, a görbét arányosan leskálázzuk rá – a negyedórák összege
így sosem több, mint amit a töltésért kiszámláztunk.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

NEGYEDORA_S = 900

MODSZER_MINTA = "meter_values"
MODSZER_ARANY = "session_aranyositas"


def _ts(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    if dt.tzinfo is None:            # SQLite / régi sor: naiv = UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def negyedora_le(t: float) -> int:
    return int(t // NEGYEDORA_S) * NEGYEDORA_S


def negyedora_fel(t: float) -> int:
    q = negyedora_le(t)
    return q if q == t else q + NEGYEDORA_S


@dataclass(frozen=True)
class SessionAdat:
    started_at: datetime
    finished_at: Optional[datetime]
    meter_start_wh: Optional[float]
    energy_kwh: Optional[float]
    # (ts, energy_wh_total) – csak a sessionhöz kötött, nem-null energiaminták
    mintak: Sequence[tuple[datetime, float]]


@dataclass(frozen=True)
class Gorbe:
    """Kumulált energia (Wh) az idő függvényében, töréspontokkal (monoton)."""
    t: list[float]
    e: list[float]
    modszer: str

    def ertek(self, x: float) -> float:
        if x <= self.t[0]:
            return self.e[0]
        if x >= self.t[-1]:
            return self.e[-1]
        i = bisect_right(self.t, x) - 1
        t0, t1 = self.t[i], self.t[i + 1]
        if t1 <= t0:
            return self.e[i + 1]
        return self.e[i] + (self.e[i + 1] - self.e[i]) * (x - t0) / (t1 - t0)


def _alap(meter_start: Optional[float], r0: float, r_utolso: float, e_hivatalos: Optional[float]) -> float:
    """Melyik alapszintről mérjük a mintákat (lásd a moduldokumentációt).

    - meterStart, ha a minták annak skáláján vannak (az első minta nem kisebb nála);
    - 0, ha a minták session-relatívak (kisebbek a meterStartnál, és nem több, mint a
      számlázott energia, 2% + 50 Wh tűréssel a regiszter-lépésekre);
    - különben az első minta.
    """
    if meter_start is not None and r0 >= float(meter_start) - 1.0:
        return float(meter_start)
    if e_hivatalos is None or r_utolso <= 1.02 * e_hivatalos + 50.0:
        return 0.0
    return r0


def session_gorbe(s: SessionAdat, *, most: float) -> Optional[Gorbe]:
    """A session kumulált energiagörbéje, vagy None, ha nincs miből számolni."""
    start = _ts(s.started_at)
    if start is None:
        return None
    vege = _ts(s.finished_at)
    e_hivatalos = float(s.energy_kwh) * 1000.0 if (vege is not None and s.energy_kwh is not None) else None
    if e_hivatalos is not None and e_hivatalos < 0:
        e_hivatalos = None

    hatar = vege if vege is not None else most
    mintak = sorted(
        ((_ts(ts), float(wh)) for ts, wh in s.mintak if ts is not None and wh is not None),
        key=lambda p: p[0],
    )
    mintak = [(t, wh) for t, wh in mintak if start <= t <= hatar]

    if mintak:
        r = []
        csucs = float("-inf")
        for _, wh in mintak:                       # a regiszter nem csökkenhet
            csucs = max(csucs, wh)
            r.append(csucs)
        base = _alap(s.meter_start_wh, r[0], r[-1], e_hivatalos)
        t = [start] + [p[0] for p in mintak]
        e = [0.0] + [max(0.0, x - base) for x in r]
        if vege is not None and e_hivatalos is not None:
            if e[-1] > e_hivatalos and e[-1] > 0:  # a számlázott energia a plafon
                k = e_hivatalos / e[-1]
                e = [x * k for x in e]
            t.append(vege)
            e.append(max(e[-1], e_hivatalos))
        # nyitott session: a görbe az utolsó mintánál véget ér (utána még nem tudunk semmit)
        return Gorbe(t=t, e=e, modszer=MODSZER_MINTA)

    if vege is not None and e_hivatalos is not None and vege > start:
        return Gorbe(t=[start, vege], e=[0.0, e_hivatalos], modszer=MODSZER_ARANY)
    return None


def negyedoras_energia(
    sessionok: Iterable[SessionAdat], *, tol: int, ig: int, most: float
) -> dict[int, tuple[float, str]]:
    """{negyedóra kezdete (unix): (Wh, módszer)} a [tol, ig) ablakra; csak ahol van adat.

    `tol`/`ig` 900-ra igazított unix-idő. Több session (több csatlakozó) egy negyedórában
    összeadódik; ha bármelyik arányosított, a sor `session_aranyositas`.
    """
    ki: dict[int, list] = {}
    for s in sessionok:
        g = session_gorbe(s, most=most)
        if g is None:
            continue
        g_eleje, g_vege = g.t[0], g.t[-1]
        a = max(tol, negyedora_le(g_eleje))
        b = min(ig, negyedora_fel(g_vege))
        q = a
        while q < b:
            x0, x1 = max(q, g_eleje), min(q + NEGYEDORA_S, g_vege)
            if x1 > x0:
                wh = max(0.0, g.ertek(x1) - g.ertek(x0))
                sor = ki.setdefault(q, [0.0, MODSZER_MINTA])
                sor[0] += wh
                if g.modszer == MODSZER_ARANY:
                    sor[1] = MODSZER_ARANY
            q += NEGYEDORA_S
    return {q: (v[0], v[1]) for q, v in sorted(ki.items())}
