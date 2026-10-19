// Interface strings around the cues. Cue text itself arrives already translated.
const STRINGS: Record<string, Record<string, string>> = {
  en: {
    player: "Player lens",
    club: "Club lens",
    pundit: "Pundit lens",
    not_involved: "not involved in this move",
    show_evidence: "Why we know",
    hide_evidence: "Hide evidence",
  },
  es: {
    player: "Lente jugador",
    club: "Lente club",
    pundit: "Lente analista",
    not_involved: "no participó en esta jugada",
    show_evidence: "Cómo lo sabemos",
    hide_evidence: "Ocultar pruebas",
  },
};

export const LANGUAGE_NAMES: Record<string, string> = { en: "English", es: "Español", fr: "Français", pt: "Português" };

export function t(lang: string, key: string): string {
  return STRINGS[lang]?.[key] ?? STRINGS.en![key] ?? key;
}
