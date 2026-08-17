// A Type 2 (AC) csatlakozó elvi felső határa – a töltők hardveresen ennyit tudnak,
// és a töltő házán is ez a szám szerepel.
//
// Több állomás viszont ez alá van korlátozva (pl. a nógrádi várnál 11 kW-ra, a helyi
// hálózati bekötés miatt). A vezető a töltő címkéje alapján 22 kW-ra számítana, ezért
// ahol a tényleges felső korlát kisebb, ott kiemelten jelezzük – a lista chipjén, a
// töltő kártyáján és a fizetés előtt is.
export const TYPE2_NOMINAL_KW = 22;

/** Igaz, ha az állomás a Type 2 nominális 22 kW alá van korlátozva. */
export function isPowerLimited(cp) {
  const kw = cp?.max_power_kw;
  return kw != null && kw > 0 && kw < TYPE2_NOMINAL_KW;
}
