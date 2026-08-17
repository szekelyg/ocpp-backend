// Egyszeri helymeghatározás – a töltő telepítésekor a telefon koordinátáit
// olvassuk be, hogy ne kézzel kelljen Google Mapsről átmásolni.

const MESSAGES = {
  1: "Helymeghatározás letiltva. Engedélyezd a böngésző beállításaiban, majd próbáld újra.",
  2: "A helymeghatározás most nem elérhető. Kint, szabad égbolt alatt pontosabb.",
  3: "Időtúllépés – nem jött meg a pozíció. Próbáld újra.",
};

/** A telepítőnek jelezzük, ha a mért pontosság ennél rosszabb (méter). */
export const ACCURACY_WARN_M = 50;

/**
 * Friss pozíció kérése. Feloldva: { latitude, longitude, accuracy }.
 *
 * maximumAge: 0 – szándékosan nincs cache. A töltő állandó helyét rögzítjük,
 * és egy korábbi, máshol felvett pozíció itt konkrétan káros lenne: a töltő
 * rossz helyre kerülne a vásárlók térképén.
 */
export function getCurrentPosition({ timeout = 15000 } = {}) {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("Ez a böngésző nem támogatja a helymeghatározást."));
      return;
    }
    // A Geolocation API csak biztonságos kontextusban (https vagy localhost) működik.
    if (window.isSecureContext === false) {
      reject(new Error("A helymeghatározáshoz https-en kell megnyitni az oldalt."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) =>
        resolve({
          latitude: p.coords.latitude,
          longitude: p.coords.longitude,
          accuracy: p.coords.accuracy,
        }),
      (e) => reject(new Error(MESSAGES[e.code] || "Nem sikerült a helymeghatározás.")),
      { enableHighAccuracy: true, timeout, maximumAge: 0 }
    );
  });
}
