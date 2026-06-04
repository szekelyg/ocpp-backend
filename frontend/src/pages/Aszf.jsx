// ÁSZF – Általános Szerződési Feltételek (Energiafelhő Kft.)
//
// FIGYELEM (fejlesztői megjegyzés, a felhasználónak nem látszik):
// A szerkezet egy szakmai elektromobilitás-ÁSZF mintát követ, a tényleges
// (web-only, regisztráció nélküli, Stripe-os) folyamatra szabva.
// Cégadatok, székhely (Ilosvai), tárhely (Cloudflare) kitöltve; telefonszám
// szándékosan nincs (kapcsolat e-mailen). Élesítés előtt ügyvédi felülvizsgálat ajánlott.
import AppHeader from "../components/ui/AppHeader";
import AppFooter from "../components/ui/AppFooter";

const HATALYOS = "2026. június 4.";

function Section({ id, n, title, children }) {
  return (
    <section id={id} className="space-y-2 scroll-mt-20">
      <h2 className="text-lg font-semibold text-slate-100">
        {n}. {title}
      </h2>
      <div className="space-y-2 text-sm text-slate-300 leading-relaxed">{children}</div>
    </section>
  );
}

function Sub({ n, children }) {
  return (
    <p className="text-sm text-slate-300 leading-relaxed">
      <span className="text-slate-500 font-mono mr-2">{n}</span>
      {children}
    </p>
  );
}

export default function Aszf() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <AppHeader />

      <main className="mx-auto max-w-3xl w-full px-6 py-8 flex-1 space-y-7">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            Általános Szerződési Feltételek (ÁSZF)
          </h1>
          <p className="text-sm text-slate-400">
            Elektromos járművek töltési szolgáltatása
          </p>
          <p className="text-sm text-slate-500">Hatályos: {HATALYOS}</p>
        </div>

        <Section n="1" title="Fogalmak">
          <p>A jelen ÁSZF-ben a nagy kezdőbetűvel írt kifejezések az alábbi jelentéssel bírnak:</p>
          <ul className="space-y-1.5">
            <li><span className="text-slate-100">„Szolgáltató"</span>: az Energiafelhő Kft., amely a Szolgáltatást nyújtja.</li>
            <li><span className="text-slate-100">„Szolgáltatás"</span>: a Szolgáltató által üzemeltetett elektromos töltőállomásokon keresztül nyújtott elektromobilitás (járműtöltési) szolgáltatás és az ahhoz kapcsolódó kiegészítő szolgáltatások.</li>
            <li><span className="text-slate-100">„Weboldal"</span>: a Szolgáltatás igénybevételére és elszámolására szolgáló online felület, amely a <span className="text-slate-100">https://ev.energiafelho.hu</span> címen érhető el.</li>
            <li><span className="text-slate-100">„Ügyfél"</span>: az a természetes vagy jogi személy, illetve jogi személyiséggel nem rendelkező szervezet, aki/amely a Szolgáltatást igénybe veszi.</li>
            <li><span className="text-slate-100">„Töltőállomás"</span>: a Szolgáltató által üzemeltetett nyilvános elektromos töltőberendezés, amely a jármű villamosenergia-tárolójának töltését biztosítja.</li>
            <li><span className="text-slate-100">„Termék"</span>: a jármű meghajtásához szükséges villamos energia.</li>
            <li><span className="text-slate-100">„Díj"</span>: a Szolgáltatásért az Ügyfél által fizetendő ellenérték.</li>
            <li><span className="text-slate-100">„Díjszabás"</span>: a Szolgáltató által a Weboldalon és/vagy a Töltőállomáson közzétett, mindenkor hatályos egységárak.</li>
            <li><span className="text-slate-100">„Zárolás"</span>: a fizetés megkezdésekor az Ügyfél bankkártyáján rögzített összeg (authorizáció), amely még nem tényleges terhelés.</li>
            <li><span className="text-slate-100">„Vis Maior"</span>: a Felek által előre nem látható, elháríthatatlan külső körülmény (pl. természeti katasztrófa, járvány, háború, áramszolgáltatói kimaradás), amely a teljesítést akadályozza.</li>
          </ul>
        </Section>

        <Section n="2" title="Általános rendelkezések">
          <Sub n="2.1">
            A jelen ÁSZF célja, hogy meghatározza a Szolgáltató és az Ügyfél közötti
            Szolgáltatás tartalmát, valamint a Szolgáltatás nyújtásának és igénybevételének
            feltételeit.
          </Sub>
          <Sub n="2.2">
            A jelen ÁSZF a Polgári Törvénykönyvről szóló 2013. évi V. törvény (Ptk.) 6:77. §-a
            szerinti általános szerződési feltételnek minősül.
          </Sub>
          <Sub n="2.3">
            A jelen ÁSZF rendelkezései a közúti közlekedésről szóló 1988. évi I. törvény (Kkt.),
            valamint az elektromobilitás szolgáltatás egyes kérdéseiről szóló 243/2019. (X.22.)
            Korm. rendelet figyelembevételével kerültek meghatározásra.
          </Sub>
          <Sub n="2.4">
            A mindenkor hatályos ÁSZF a Weboldalon érhető el, oly módon, hogy az Ügyfél
            azt tárolhatja és előhívhatja. A Szolgáltató fenntartja a jogot az ÁSZF egyoldalú,
            alapos okból történő módosítására; a módosított ÁSZF a Weboldalon való
            közzététellel lép hatályba.
          </Sub>
        </Section>

        <Section n="3" title="A Szolgáltató adatai">
          <ul className="space-y-1">
            <li>Cégnév: <span className="text-slate-100">Energiafelhő Kft.</span> (Energiafelhő Korlátolt Felelősségű Társaság)</li>
            <li>Székhely: <span className="text-slate-100">1147 Budapest, Ilosvai Selymes utca 127. fszt. 2.</span></li>
            <li>Cégjegyzékszám: <span className="text-slate-100">01-09-953931</span></li>
            <li>Adószám: <span className="text-slate-100">23120635-2-42</span></li>
            <li>E-mail: <a className="text-blue-400" href="mailto:szerviz@energiafelho.hu">szerviz@energiafelho.hu</a></li>
            <li>Tárhelyszolgáltató: <span className="text-slate-100">Cloudflare, Inc.</span> (101 Townsend Street, San Francisco, CA 94107, USA)</li>
          </ul>
        </Section>

        <Section n="4" title="A szerződés létrejötte, elfogadás">
          <Sub n="4.1">
            A Szolgáltatás regisztráció nélkül, az Ügyfél e-mail-címének és számlázási
            adatainak megadásával, bankkártyás fizetéssel vehető igénybe.
          </Sub>
          <Sub n="4.2">
            A Felek közötti szerződés a Szolgáltatás igénybevételével, így különösen a fizetés
            kezdeményezésével és a sikeres Zárolással jön létre. A Szolgáltatás
            igénybevételével az Ügyfél kijelenti, hogy a jelen ÁSZF-et megismerte és
            elfogadja.
          </Sub>
          <Sub n="4.3">
            A Szolgáltatást cselekvőképes, nagykorú természetes személyek saját nevükben,
            jogi személyek és szervezetek képviselőjük útján vehetik igénybe.
          </Sub>
        </Section>

        <Section n="5" title="A Szolgáltatás tartalma és igénybevétele">
          <Sub n="5.1">A Szolgáltatás igénybevételének lépései a Weboldalon keresztül:</Sub>
          <ul className="list-disc pl-6 space-y-1">
            <li>az Ügyfél kiválasztja a Töltőállomást a térképen/listában;</li>
            <li>megadja az e-mail-címét és a számlázási adatait;</li>
            <li>a bankkártyáján a választott összeg Zárolásra kerül;</li>
            <li>a rendszer elindítja a töltést, az Ügyfél csatlakoztatja a járművet;</li>
            <li>a töltés az Ügyfél által vagy a jármű töltöttsége alapján leáll.</li>
          </ul>
          <Sub n="5.2">
            A Töltőállomáshoz tartozó parkolóterület kizárólag a tényleges töltés idejére
            vehető igénybe; a töltés befejezését követően az Ügyfél köteles azt elhagyni.
          </Sub>
          <Sub n="5.3">
            A Szolgáltató jogosult a Szolgáltatás nyújtását karbantartás, hatósági előírás,
            vagy az ÁSZF Ügyfél általi megsértése esetén korlátozni, felfüggeszteni vagy
            megszüntetni. A tervezett karbantartásról a Szolgáltató lehetőség szerint
            előzetesen tájékoztat a Weboldalon.
          </Sub>
        </Section>

        <Section n="6" title="Díjak és díjfizetés">
          <Sub n="6.1">
            A Szolgáltatás Díja a felhasznált villamos energia mennyisége (kWh) és a
            Töltőállomáson, illetve a Weboldalon feltüntetett, mindenkor hatályos Díjszabás
            alapján kerül kiszámításra. A feltüntetett ár az általános forgalmi adót (ÁFA)
            tartalmazza.
          </Sub>
          <Sub n="6.2">
            A fizetés megkezdésekor a Szolgáltató az Ügyfél által választott összeget zárolja
            a bankkártyán (authorizáció). Amennyiben a fedezet nem áll rendelkezésre, a
            töltési kérés elutasításra kerül.
          </Sub>
          <Sub n="6.3">
            A töltés befejezésekor a Szolgáltató kizárólag a ténylegesen felhasznált energia
            ellenértékét vonja le; a Zárolás fennmaradó része feloldásra kerül. A Szolgáltató
            a zárolt összeget nem tartja vissza; a felszabadítás tényleges időpontja az Ügyfél
            számlavezető bankjától függ.
          </Sub>
          <Sub n="6.4">
            A legkisebb levonható összeg <span className="text-slate-100">500 Ft</span>. Nagyon
            rövid töltés esetén is legalább ennyi kerül felszámításra. A levont összeg nem
            haladhatja meg a zárolt összeget.
          </Sub>
          <Sub n="6.5">
            Amennyiben a fizetést követő 15 percen belül a töltés nem indul el (pl. a jármű nem
            kerül csatlakoztatásra), a Zárolás feloldásra, illetve az esetleges terhelés
            visszatérítésre kerül.
          </Sub>
          <Sub n="6.6">
            Az online bankkártyás fizetést a <span className="text-slate-100">Stripe</span>{" "}
            (Stripe Payments Europe, Ltd.) biztosítja. A kártyaadatok a Szolgáltatóhoz nem
            jutnak el, azokat kizárólag a Stripe kezeli, titkosított módon.
          </Sub>
          <Sub n="6.7">
            A teljesítésről a Szolgáltató elektronikus számlát állít ki (a számlázz.hu
            rendszerén keresztül), amelyet az Ügyfél által megadott e-mail-címre küld meg. A
            számlázási adatok pontos megadása az Ügyfél felelőssége.
          </Sub>
          <Sub n="6.8">
            Amennyiben a fizetés technikai hiba miatt meghiúsul, az igénybe vett, de ki nem
            fizetett Szolgáltatás ellenértékét az Ügyfél köteles utólag, a Szolgáltató e-mailben
            megküldött felhívása alapján rendezni.
          </Sub>
        </Section>

        <Section n="7" title="Elállás, visszatérítés, fogyasztói tájékoztatás">
          <Sub n="7.1">
            A Szolgáltatás energiaértékesítés, amely a teljesítés megkezdésével azonnal
            teljesül. A fogyasztó és a vállalkozás közötti szerződések részletes szabályairól
            szóló 45/2014. (II.26.) Korm. rendelet alapján a már megkezdett töltésre az
            elállási/felmondási jog nem gyakorolható.
          </Sub>
          <Sub n="7.2">
            Hibás teljesítés vagy téves terhelés esetén az Ügyfél az{" "}
            <a className="text-blue-400" href="mailto:szerviz@energiafelho.hu">szerviz@energiafelho.hu</a>{" "}
            címen élhet igénnyel; a Szolgáltató a jogos igényt visszatéríti.
          </Sub>
        </Section>

        <Section n="8" title="Felelősség">
          <Sub n="8.1">
            A Szolgáltató szerződésszegéssel okozott károkért való felelősségére a Ptk.
            rendelkezései az irányadók. A Szolgáltató kizárja a felelősségét a
            szerződésszegés következményeként az Ügyfél vagyonában keletkezett egyéb
            károkért és az elmaradt vagyoni előnyért, a jogszabály által megengedett
            mértékben.
          </Sub>
          <Sub n="8.2">
            A Szolgáltató nem felel a Töltőállomás átmeneti üzemszünetéért, az elektronikus
            hírközlési vagy áramszolgáltatói hibákból, illetve Vis Maiorból eredő
            kimaradásokért.
          </Sub>
          <Sub n="8.3">
            Az Ügyfél felelős azért, hogy a Szolgáltatást rendeltetésszerűen, hibátlan
            állapotú járművel és ép, szabványos csatlakozóval/kábellel vegye igénybe. Az
            Ügyfél a szerződésszegésével vagy a nem rendeltetésszerű használatával okozott
            károkért teljes felelősséggel tartozik.
          </Sub>
          <Sub n="8.4">
            Nem minősül szerződésszegésnek, ha valamelyik Fél Vis Maior miatt nem tudja
            teljesíteni a kötelezettségeit. A Vis Maiorról a Felek egymást haladéktalanul
            tájékoztatni kötelesek.
          </Sub>
        </Section>

        <Section n="9" title="Ügyfélszolgálat és hibabejelentés">
          <Sub n="9.1">
            Az Ügyfél a Szolgáltatással kapcsolatos kérdéseit, illetve a tapasztalt hibákat az{" "}
            <a className="text-blue-400" href="mailto:szerviz@energiafelho.hu">szerviz@energiafelho.hu</a>{" "}
            e-mail-címen jelentheti be a Szolgáltató felé.
          </Sub>
        </Section>

        <Section n="10" title="Panaszkezelés és jogérvényesítés">
          <Sub n="10.1">
            Az Ügyfél panaszával írásban fordulhat a Szolgáltatóhoz a fenti e-mail-címen. A
            Szolgáltató a panaszt a beérkezéstől számított 30 napon belül kivizsgálja és
            érdemben megválaszolja.
          </Sub>
          <Sub n="10.2">
            Fogyasztói jogvita esetén az Ügyfél a lakóhelye szerint illetékes békéltető
            testülethez fordulhat (a fogyasztóvédelemről szóló 1997. évi CLV. törvény szerint),
            valamint igénybe veheti az Európai Bizottság online vitarendezési platformját:{" "}
            <a className="text-blue-400" href="https://ec.europa.eu/odr" target="_blank" rel="noreferrer">ec.europa.eu/odr</a>.
          </Sub>
        </Section>

        <Section n="11" title="Adatkezelés">
          <Sub n="11.1">
            A Szolgáltató az Ügyfél által megadott e-mail-címet és számlázási adatokat a
            szerződés teljesítése és a számlázás céljából kezeli, az Európai Parlament és a
            Tanács (EU) 2016/679 rendeletével (GDPR) összhangban. A fizetési adatokat a
            Stripe kezeli.
          </Sub>
          <Sub n="11.2">
            Az adatkezelés részletes szabályait a külön{" "}
            <a className="text-blue-400" href="/adatkezeles">Adatkezelési tájékoztató</a>{" "}
            tartalmazza, amely a Weboldalon érhető el.
          </Sub>
        </Section>

        <Section n="12" title="Záró rendelkezések">
          <Sub n="12.1">
            A jelen ÁSZF-re és a Felek közötti szerződésre a magyar jog az irányadó.
          </Sub>
          <Sub n="12.2">
            A Felek a jogvitáikat elsősorban békés úton kísérlik meg rendezni; ennek
            eredménytelensége esetén a polgári perrendtartásról szóló 2016. évi CXXX. törvény
            rendelkezései irányadók.
          </Sub>
          <Sub n="12.3">
            Amennyiben a jelen ÁSZF valamely rendelkezése érvénytelennek minősül, az a
            többi rendelkezés érvényességét nem érinti.
          </Sub>
          <Sub n="12.4">
            A jelen ÁSZF-fel összefüggő bármely értesítés vagy közlés magyar nyelven érvényes.
          </Sub>
        </Section>

        <div className="pt-2">
          <a href="/" className="text-sm text-slate-500 hover:text-slate-300 transition">
            ← Vissza a főoldalra
          </a>
        </div>
      </main>

      <AppFooter />
    </div>
  );
}
