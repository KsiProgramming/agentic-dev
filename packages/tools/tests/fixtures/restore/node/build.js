// The build job has no network: a request must fail. esbuild is a native module, so
// `pnpm rebuild` ran its install script offline and it can bundle.
const esbuild = require("esbuild");
const isOdd = require("is-odd");
const fs = require("fs");

async function main() {
  if (fs.existsSync("preinstall-ran-online")) {
    console.error("a lifecycle script ran during the restore");
    process.exit(5);
  }
  try {
    await fetch("https://example.com", { signal: AbortSignal.timeout(5000) });
    console.error("the build job reached the network");
    process.exit(3);
  } catch {
    // expected: no route out
  }
  const out = esbuild.buildSync({
    stdin: { contents: `console.log(${isOdd(3)})` },
    write: false,
  });
  if (out.outputFiles.length !== 1) process.exit(4);
}

main();
