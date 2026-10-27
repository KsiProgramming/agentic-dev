/** Where the density toggle keeps its choice ("compact" or "comfortable"). */
export const DENSITY_KEY = "density";

/** Puts the stored density on `<html>` before the first paint; the root layout inlines it. */
export const DENSITY_SCRIPT = `(function(){try{if(localStorage.getItem("${DENSITY_KEY}")==="compact")document.documentElement.classList.add("compact")}catch(e){}})()`;
