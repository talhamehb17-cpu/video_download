"""Platform integrations: which websites this service knows, and what state each is in.

* :mod:`catalog` - the built-in list (name, addresses, what to expect).
* :mod:`registry` - the catalog plus the operator's decisions and the results of
  compatibility checks, kept in a small JSON file.

Adding a platform means adding one entry to the catalog (or one row in the admin
panel). Reading a video is always done by the maintained yt-dlp extractor for that
website; nothing here scrapes pages itself.
"""
