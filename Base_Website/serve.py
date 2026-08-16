#!/usr/bin/env python3
"""
Static dev server for the storefront, with caching turned off.

Use this instead of `python3 -m http.server 8080`.

Why it exists: the plain module sends no Cache-Control and no ETag, only
Last-Modified. Chrome is then free to serve some files from cache and refetch
others, which mixes versions of files that are meant to change together. That
produced a genuinely confusing failure -- an updated render-home.js calling
productImage() against a cached placeholder.js that predated the function threw
"productImage is not defined", the render aborted, and the page showed no
product images at all rather than an obvious error.

Sending no-store means a plain reload always picks up edits, so a stale asset
can never silently break the page again.

    python3 serve.py [port]        # defaults to 8080
"""

import functools
import http.server
import os
import sys


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    # Declare UTF-8 on text responses. Without it a classic script inherits the
    # document's encoding, so a page that forgets <meta charset> renders any
    # non-ASCII character in the JS (the "·" separators in the cart, the em
    # dashes in copy) as mojibake. Stating it here removes the dependency.
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml; charset=utf-8",
    }

    def end_headers(self):
        # no-store: don't write to cache at all. Belt-and-braces headers for
        # older browsers that ignore it.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Quieter than the default: 404s are what matter when assets go missing.
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    root = os.path.dirname(os.path.abspath(__file__))
    handler = functools.partial(NoCacheHandler, directory=root)
    # Bind every interface, matching `python3 -m http.server`. Binding only
    # 127.0.0.1 breaks http://[::1]:8080, which is where a browser may land
    # first when resolving "localhost" on macOS.
    with http.server.ThreadingHTTPServer(("", port), handler) as httpd:
        print(f"Serving {root} at http://localhost:{port}/  (caching disabled)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
