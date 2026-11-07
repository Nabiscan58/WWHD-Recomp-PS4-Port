// PS4: no downloads from inside the game (the mod catalogue, the story notebook's package). Install mods on the PC
// with the Maker instead. host::download_https throws, as the desktop builds do when a download fails.
#include "platform/https.h"

#include "exception_report.h"

namespace host {
void download_https(const std::string& url, const std::filesystem::path&, uint64_t) {
    exception_report::raise("downloads are not available on the PS4 (" + url + ")");
}
}  // namespace host
