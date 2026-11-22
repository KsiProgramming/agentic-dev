// Lifecycle scripts run in the build job, which has no network. This one leaves a marker only if
// it ran while the registry proxy was set, that is, during the restore, which must run no script.
if (process.env.HTTPS_PROXY) {
  require("fs").writeFileSync("preinstall-ran-online", "x");
}
