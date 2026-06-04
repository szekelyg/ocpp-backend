// Adatkezelési tájékoztató (Energiafelhő Kft.) – GDPR-konform
//
// FIGYELEM (fejlesztői megjegyzés, a felhasználónak nem látszik):
// A minta egy régebbi (Infotv.-alapú) szabályzat volt; ez modern, GDPR-alapú
// tájékoztató, a tényleges adatfeldolgozókkal (Stripe, számlázz.hu/KBOSS, Resend, Cloudflare).
// Telefonszám szándékosan nincs. Élesítés előtt ügyvédi/adatvédelmi felülvizsgálat ajánlott.
import AppHeader from "../components/ui/AppHeader";
import AppFooter from "../components/ui/AppFooter";

const HATALYOS = "2026. június 4.";

function Section({ n, title, children }) {
  return (
    <section className="space-y-2 scroll-mt-20">
      <h2 className="text-lg font-semibold text-slate-100">
        {n}. {title}
      </h2>
      <div className="space-y-2 text-sm text-slate-300 leading-relaxed">{children}</div>
    </section>
  );
}

function Row({ a, b, c }) {
  return (
    <tr className="border-t border-slate-800 align-top">
      <td className="py-2 pr-3 text-slate-200">{a}</td>
      <td className="py-2 pr-3">{b}</td>
      <td className="py-2">{c}</td>
    </tr>
  );
}

export default function Adatkezeles() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <AppHeader />

      <main className="mx-auto max-w-3xl w-full px-6 py-8 flex-1 space-y-7">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Adatkezelési tájékoztató</h1>
          <p className="text-sm text-slate-400">
            Az elektromos töltési szolgáltatás adatkezelése (GDPR)
          </p>
          <p className="text-sm text-slate-500">Hatályos: {HATALYOS}</p>
        </div>

        <p className="text-sm text-slate-300 leading-relaxed">
          A jelen tájékoztató az Energiafelhő Kft. által a{" "}
          <span className="text-slate-100">https://ev.energiafelho.hu</span> oldalon nyújtott
          elektromos töltési szolgáltatás keretében végzett személyesadat-kezelésről
          tájékoztatja az érintetteket, az Európai Parlament és a Tanács (EU) 2016/679
          rendelete (GDPR) és az információs önrendelkezési jogról szóló 2011. évi CXII.
          törvény (Infotv.) alapján.
        </p>

        <Section n="1" title="Az adatkezelő">
          <ul className="space-y-1">
            <li>Cégnév: <span className="text-slate-100">Energiafelhő Kft.</span></li>
            <li>Székhely: <span className="text-slate-100">1147 Budapest, Ilosvai Selymes utca 127. fszt. 2.</span></li>
            <li>Cégjegyzékszám: <span className="text-slate-100">01-09-953931</span></li>
            <li>Adószám: <span className="text-slate-100">23120635-2-42</span></li>
            <li>E-mail: <a className="text-blue-400" href="mailto:szerviz@energiafelho.hu">szerviz@energiafelho.hu</a></li>
          </ul>
          <p>Az adatkezelő adatvédelmi tisztviselő kijelölésére nem köteles, és ilyet nem jelölt ki.</p>
        </Section>

        <Section n="2" title="A kezelt adatok köre">
          <ul className="list-disc pl-6 space-y-1">
            <li>e-mail-cím (a töltés indításához és az értesítésekhez);</li>
            <li>számlázási adatok: név vagy cégnév, számlázási cím (irányítószám, település, utca), céges vásárló esetén adószám;</li>
            <li>a töltési tranzakció adatai: a töltőállomás azonosítója, időpont, felhasznált energia (kWh), fizetendő/levont összeg, számlaszám;</li>
            <li>fizetéssel kapcsolatos azonosítók (a kártyaadatokat kizárólag a fizetési szolgáltató, a Stripe kezeli – azokhoz az adatkezelő nem fér hozzá);</li>
            <li>technikai adatok: a kapcsolódáshoz szükséges, automatikusan keletkező adatok (pl. IP-cím, eszköz-/böngészőadatok) a szolgáltatás működéséhez és biztonságához szükséges mértékben.</li>
          </ul>
        </Section>

        <Section n="3" title="Az adatkezelés célja, jogalapja és időtartama">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400">
                  <th className="py-1.5 pr-3 font-medium">Cél</th>
                  <th className="py-1.5 pr-3 font-medium">Jogalap (GDPR)</th>
                  <th className="py-1.5 font-medium">Időtartam</th>
                </tr>
              </thead>
              <tbody>
                <Row
                  a="A töltési szolgáltatás nyújtása, a töltés indítása és elszámolása"
                  b="Szerződés teljesítése – 6. cikk (1) b)"
                  c="A szerződés teljesítéséig, illetve az igények elévüléséig (5 év)"
                />
                <Row
                  a="Számla kiállítása és megőrzése"
                  b="Jogi kötelezettség – 6. cikk (1) c) (számviteli tv.)"
                  c="A számviteli törvény szerint 8 év"
                />
                <Row
                  a="Értesítő és bizonylat e-mailek küldése"
                  b="Szerződés teljesítése – 6. cikk (1) b)"
                  c="A szerződés teljesítéséig"
                />
                <Row
                  a="A szolgáltatás működése, biztonsága, visszaélések megelőzése"
                  b="Jogos érdek – 6. cikk (1) f)"
                  c="A cél eléréséhez szükséges ideig"
                />
              </tbody>
            </table>
          </div>
        </Section>

        <Section n="4" title="Adatfeldolgozók és címzettek">
          <p>Az adatkezelő a szolgáltatás nyújtásához az alábbi adatfeldolgozókat veszi igénybe:</p>
          <ul className="list-disc pl-6 space-y-1.5">
            <li>
              <span className="text-slate-100">Stripe Payments Europe, Ltd.</span> (1 Grand Canal
              Street Lower, Grand Canal Dock, Dublin, Írország) – online bankkártyás fizetés
              feldolgozása. A kártyaadatokat kizárólag a Stripe kezeli.
            </li>
            <li>
              <span className="text-slate-100">KBOSS.hu Kft. (Számlázz.hu)</span> (1031 Budapest,
              Záhony utca 7.) – elektronikus számla kiállítása és kézbesítése.
            </li>
            <li>
              <span className="text-slate-100">Resend, Inc.</span> (USA) – a szolgáltatáshoz
              kapcsolódó e-mailek (értesítők, bizonylatok) kézbesítése. Az Egyesült Államokba
              irányuló adattovábbítás a GDPR szerinti megfelelő garanciák mellett történik.
            </li>
            <li>
              <span className="text-slate-100">Cloudflare, Inc.</span> (101 Townsend Street, San
              Francisco, CA 94107, USA) – tárhely-/infrastruktúra-szolgáltatás, a forgalom
              továbbítása és biztonsága. Az Egyesült Államokba irányuló adattovábbítás a GDPR
              szerinti megfelelő garanciák mellett történik.
            </li>
          </ul>
          <p>
            A személyes adatokhoz az adatkezelőn (és munkatársain) kívül harmadik személy
            csak jogszabály vagy hatósági/bírósági megkeresés alapján fér hozzá.
          </p>
        </Section>

        <Section n="5" title="Adatbiztonság">
          <p>
            Az adatkezelő megteszi a kockázattal arányos technikai és szervezési
            intézkedéseket az adatok védelme érdekében (pl. titkosított adatátvitel, hozzáférés
            korlátozása). A bankkártyaadatok az adatkezelő rendszerébe nem kerülnek be.
          </p>
        </Section>

        <Section n="6" title="Az érintett jogai">
          <p>Az érintett a GDPR szerint az alábbi jogokkal élhet:</p>
          <ul className="list-disc pl-6 space-y-1">
            <li>tájékoztatáshoz és hozzáféréshez való jog;</li>
            <li>helyesbítéshez való jog;</li>
            <li>törléshez való jog („elfeledtetés"), a jogi kötelezettség (pl. számlamegőrzés) korlátai között;</li>
            <li>az adatkezelés korlátozásához való jog;</li>
            <li>tiltakozáshoz való jog a jogos érdeken alapuló adatkezelés ellen;</li>
            <li>adathordozhatósághoz való jog;</li>
            <li>hozzájárulás visszavonása (a visszavonás a korábbi adatkezelés jogszerűségét nem érinti).</li>
          </ul>
          <p>
            Az érintett a jogait az{" "}
            <a className="text-blue-400" href="mailto:szerviz@energiafelho.hu">szerviz@energiafelho.hu</a>{" "}
            címen gyakorolhatja. Az adatkezelő a kérelmet indokolatlan késedelem nélkül, de
            legkésőbb 1 hónapon belül teljesíti.
          </p>
        </Section>

        <Section n="7" title="Jogorvoslat">
          <p>
            Az érintett panaszával a Nemzeti Adatvédelmi és Információszabadság Hatósághoz
            (NAIH) fordulhat:
          </p>
          <ul className="space-y-0.5">
            <li>Cím: 1055 Budapest, Falk Miksa utca 9-11.</li>
            <li>Postacím: 1363 Budapest, Pf. 9.</li>
            <li>E-mail: <a className="text-blue-400" href="mailto:ugyfelszolgalat@naih.hu">ugyfelszolgalat@naih.hu</a></li>
            <li>Web: <a className="text-blue-400" href="https://naih.hu" target="_blank" rel="noreferrer">naih.hu</a></li>
          </ul>
          <p>Az érintett a jogainak megsértése esetén bírósághoz is fordulhat.</p>
        </Section>

        <Section n="8" title="Sütik (cookie-k) és technikai adatok">
          <p>
            A weboldal a működéséhez szükséges technikai adatokat használ. A szolgáltatás nem
            alkalmaz marketing- vagy profilalkotási célú sütiket. Amennyiben a jövőben
            statisztikai vagy egyéb sütik kerülnek bevezetésre, a tájékoztató ennek megfelelően
            frissül.
          </p>
        </Section>

        <Section n="9" title="A tájékoztató módosítása">
          <p>
            Az adatkezelő fenntartja a jogot a jelen tájékoztató egyoldalú módosítására; a
            mindenkor hatályos verzió a weboldalon érhető el.
          </p>
        </Section>

        <div className="pt-2 flex flex-wrap gap-4">
          <a href="/aszf" className="text-sm text-slate-500 hover:text-slate-300 transition">
            ÁSZF
          </a>
          <a href="/" className="text-sm text-slate-500 hover:text-slate-300 transition">
            ← Vissza a főoldalra
          </a>
        </div>
      </main>

      <AppFooter />
    </div>
  );
}
