"""Voice input (speech-to-text) and multilingual support.

- token.py        -- Azure Speech: mints short-lived browser tokens (the only
                     file that talks to the Speech service).
- translation.py  -- Azure Translator REST wrapper (the only file that talks
                     to the Translator service).
- multilingual.py -- translate-at-the-edges orchestration: user text in any
                     language -> English for the pipeline -> reply back in
                     the user's language. No vendor calls of its own.

Speech recognition itself happens in the browser (Speech SDK + the token);
no audio ever reaches this backend. Text-to-speech is deliberately out of
scope.
"""
