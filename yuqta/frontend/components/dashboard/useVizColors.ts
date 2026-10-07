"use client";

import { useSyncExternalStore } from "react";

// Validated with the dataviz palette checker against our chart surfaces
// (light #ffffff, dark #161e1b): all checks pass in both modes.
const LIGHT = {
  previous: "#2a78d6", // categorical slot 1
  current: "#eb6834", // categorical slot 2
  decline: "#008300", // single series
  share: "#2a78d6", // single series (who spoke)
  grid: "#e5e9e4",
  axis: "#64716b",
  text: "#172420",
  surface: "#ffffff",
} as const;

const DARK = {
  previous: "#3987e5",
  current: "#d95926",
  decline: "#008300",
  share: "#3987e5",
  grid: "#26322d",
  axis: "#93a19a",
  text: "#e8eeeb",
  surface: "#161e1b",
} as const;

export type VizColors = { [K in keyof typeof LIGHT]: string };

const QUERY = "(prefers-color-scheme: dark)";

function subscribe(callback: () => void) {
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}

/** SVG fill attributes can't reliably use CSS variables, so pick hex values by color scheme. */
export function useVizColors(): VizColors {
  const dark = useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => false,
  );
  return dark ? DARK : LIGHT;
}
