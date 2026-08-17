// Gyakori kérdések – a fizetési modal szövegeivel összhangban.
const FAQ = [
  {
    q: "Kell regisztrálni vagy applikációt letölteni?",
    a: "Nem. A töltés böngészőből indítható, bankkártyás fizetéssel. Ha szeretné, a fizetésnél elmentheti a számlázási adatait, így legközelebb elég belépnie az email-címével — kártyaadatot soha nem tárolunk.",
  },
  {
    q: "Hogyan fizetek, és mikor vonják le a pénzt?",
    a: "Indításkor a kártyáján zárolásra kerül egy választott keret — tényleges terhelés ekkor még nem történik. A töltés végén kizárólag a felhasznált energia díját vonjuk le, a maradék zárolás automatikusan felszabadul.",
  },
  {
    q: "Kapok számlát?",
    a: "Igen, a töltés végén elektronikus számlát küldünk a megadott email-címre. Céges (ÁFA-s) számlához a fizetésnél válassza a „Céges” lehetőséget, és adja meg a cégnevet és az adószámot.",
  },
  {
    q: "Mi történik, ha végül nem töltök semmit?",
    a: "Ha a töltés el sem indul, a zárolt összeg felszabadul, és nem történik levonás. Nagyon rövid töltésnél a bankkártyás feldolgozás minimuma kerül levonásra — ennek összege az állomásnál és a fizetés előtt is látható.",
  },
  {
    q: "Milyen autóval és csatlakozóval tölthetek?",
    a: "Állomásaink Type 2 (AC) csatlakozóval rendelkeznek. A felső teljesítmény-korlát állomásonként eltér — van, ahol a helyi hálózati bekötés miatt kevesebb, mint amennyit a töltő önmagában tudna. Mindig a kiválasztott töltő kártyáján szereplő „Max. teljesítmény” érvényes, ezt a fizetés előtt is kiírjuk. A tényleges töltési teljesítményt ezen felül az autó fedélzeti töltője is behatárolja.",
  },
  {
    q: "Mi van, ha hibát tapasztalok vagy megszakad a töltés?",
    a: "Megszakadt töltésnél csak a ténylegesen felhasznált energiát számoljuk el. Ha bármilyen problémát tapasztal, hívja ügyfélszolgálatunkat a +36 1 300 9045 számon, vagy írjon a szerviz@energiafelho.hu címre.",
  },
];

export default function FaqSection() {
  return (
    <div className="card">
      <div className="cardHeader">
        <div className="cardTitle">Gyakori kérdések</div>
        <div className="cardSub mt-0.5">Minden, amit a töltésről és a fizetésről tudni érdemes</div>
      </div>
      <div className="px-5 py-2 divide-y divide-brand-line">
        {FAQ.map(({ q, a }) => (
          <details key={q} className="group py-3">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-ink [&::-webkit-details-marker]:hidden">
              {q}
              <span className="shrink-0 text-ink-muted transition-transform group-open:rotate-45">＋</span>
            </summary>
            <p className="mt-2 text-sm text-ink-soft leading-relaxed">{a}</p>
          </details>
        ))}
      </div>
    </div>
  );
}
