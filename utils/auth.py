"""
Optional Google/GitHub OAuth login, built with Authlib.

This is fully functional code, but it needs credentials that only you can
create (I can't register an OAuth app on your behalf):

  Google: https://console.cloud.google.com/apis/credentials
    -> Create OAuth client ID -> Web application
    -> Authorized redirect URI: http://127.0.0.1:5000/auth/google/callback
    -> copy the Client ID + Client Secret into .env as GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET

  GitHub: https://github.com/settings/developers -> New OAuth App
    -> Authorization callback URL: http://127.0.0.1:5000/auth/github/callback
    -> copy the Client ID + Client Secret into .env as GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET

If neither is configured, the app runs exactly as before: an anonymous
per-browser session id, no login required. This is intentional - a
final-year project demo shouldn't hard-require OAuth credentials just to
run locally.
"""

import os
from authlib.integrations.flask_client import OAuth

oauth = OAuth()


def is_oauth_configured() -> bool:
    return bool(
        (os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))
        or (os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET"))
    )


def init_oauth(app):
    oauth.init_app(app)

    if os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    if os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET"):
        oauth.register(
            name="github",
            client_id=os.getenv("GITHUB_CLIENT_ID"),
            client_secret=os.getenv("GITHUB_CLIENT_SECRET"),
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email"},
        )
