import socket
from urllib.parse import unquote, urlparse, urlunparse

import base64
import hashlib
import re

import flask
from flask import render_template, request
import prometheus_client
import user_agents
import webapp.template_utils as template_utils
from canonicalwebteam import image_template
from webapp import authentication
import webapp.helpers as helpers
from webapp.config import (
    BSI_URL,
    LOGIN_URL,
    SENTRY_DSN,
    COMMIT_ID,
    ENVIRONMENT,
    WEBAPP_CONFIG,
    DNS_VERIFICATION_SALT,
)

from canonicalwebteam.exceptions import (
    StoreApiError,
    StoreApiConnectionError,
    StoreApiResourceNotFound,
    StoreApiResponseDecodeError,
    StoreApiResponseError,
    StoreApiResponseErrorList,
    StoreApiTimeoutError,
    PublisherAgreementNotSigned,
    PublisherMacaroonRefreshRequired,
    PublisherMissingUsername,
)

from webapp.api.exceptions import (
    ApiError,
    ApiConnectionError,
    ApiResponseErrorList,
    ApiTimeoutError,
    ApiResponseDecodeError,
    ApiResponseError,
)

from datetime import datetime

badge_counter = prometheus_client.Counter(
    "badge_counter", "A counter of badges requests"
)

badge_logged_in_counter = prometheus_client.Counter(
    "badge_logged_in_counter",
    "A counter of badges requests of logged in users",
)

accept_encoding_counter = prometheus_client.Counter(
    "accept_encoding_counter",
    "A counter for Accept-Encoding headers, split by browser",
    ["accept_encoding", "browser_family"],
)

CSP = {
    "default-src": ["'self'"],
    "img-src": [
        "data: blob:",
        # This is needed to allow images from
        # https://www.google.*/ads/ga-audiences to load.
        "*",
    ],
    "script-src-elem": [
        "'self'",
        "assets.ubuntu.com",
        "www.googletagmanager.com",
        "www.youtube.com",
        "asciinema.org",
        "player.vimeo.com",
        "plausible.io",
        "script.crazyegg.com",
        "w.usabilla.com",
        "connect.facebook.net",
        "snap.licdn.com",
        # This is necessary for Google Tag Manager to function properly.
        "'unsafe-inline'",
    ],
    "font-src": [
        "'self'",
        "assets.ubuntu.com",
    ],
    "script-src": [],
    "connect-src": [
        "'self'",
        "ubuntu.com",
        "analytics.google.com",
        "stats.g.doubleclick.net",
        "www.googletagmanager.com",
        "sentry.is.canonical.com",
        "www.google-analytics.com",
        "plausible.io",
        "*.crazyegg.com",
        "www.facebook.com",
        "px.ads.linkedin.com",
    ],
    "frame-src": [
        "'self'",
        "td.doubleclick.net",
        "www.youtube.com/",
        "asciinema.org",
        "player.vimeo.com",
        "snapcraft.io",
        "www.facebook.com",
        "snap:",
    ],
    "style-src": [
        "'self'",
        "'unsafe-inline'",
    ],
    "media-src": [
        "'self'",
        "res.cloudinary.com",
    ],
}

CSP_SCRIPT_SRC = [
    "'self'",
    "blob:",
    "'unsafe-eval'",
    "'unsafe-hashes'",
]


def refresh_redirect(path):
    try:
        macaroon_discharge = authentication.get_refreshed_discharge(
            flask.session["macaroon_discharge"]
        )
    except ApiResponseError as api_response_error:
        if api_response_error.status_code == 401:
            return flask.redirect(flask.url_for("login.logout"))
        else:
            return flask.abort(502, str(api_response_error))
    except ApiError as api_error:
        return flask.abort(502, str(api_error))

    flask.session["macaroon_discharge"] = macaroon_discharge
    return flask.redirect(path)


def snapcraft_utility_processor():
    if authentication.is_authenticated(flask.session):
        user_name = flask.session["publisher"]["fullname"]
        user_is_canonical = flask.session["publisher"].get(
            "is_canonical", False
        )
        stores = flask.session["publisher"].get("stores")
    else:
        user_name = None
        user_is_canonical = False
        stores = []

    page_slug = template_utils.generate_slug(flask.request.path)

    return {
        # Variables
        "LOGIN_URL": LOGIN_URL,
        "SENTRY_DSN": SENTRY_DSN,
        "COMMIT_ID": COMMIT_ID,
        "ENVIRONMENT": ENVIRONMENT,
        "host_url": flask.request.host_url,
        "path": flask.request.path,
        "page_slug": page_slug,
        "user_name": user_name,
        "VERIFIED_PUBLISHER": "verified",
        "STAR_DEVELOPER": "starred",
        "webapp_config": WEBAPP_CONFIG,
        "BSI_URL": BSI_URL,
        "now": datetime.now(),
        "user_is_canonical": user_is_canonical,
        # Functions
        "contains": template_utils.contains,
        "join": template_utils.join,
        "static_url": template_utils.static_url,
        "format_number": template_utils.format_number,
        "format_display_name": template_utils.format_display_name,
        "display_name": template_utils.display_name,
        "install_snippet": template_utils.install_snippet,
        "format_date": template_utils.format_date,
        "format_member_role": template_utils.format_member_role,
        "image": image_template,
        "stores": stores,
        "format_link": template_utils.format_link,
        "DNS_VERIFICATION_SALT": DNS_VERIFICATION_SALT,
    }


def set_handlers(app):
    @app.context_processor
    def utility_processor():
        """
        This defines the set of properties and functions that will be added
        to the default context for processing templates. All these items
        can be used in all templates
        """

        return snapcraft_utility_processor()

    # Error handlers
    # ===
    @app.errorhandler(500)
    @app.errorhandler(501)
    @app.errorhandler(502)
    @app.errorhandler(504)
    @app.errorhandler(505)
    def internal_error(error):
        error_name = getattr(error, "name", type(error).__name__)
        return_code = getattr(error, "code", 500)

        if not app.testing:
            app.extensions["sentry"].captureException()

        return (
            flask.render_template("50X.html", error_name=error_name),
            return_code,
        )

    @app.errorhandler(503)
    def service_unavailable(error):
        return render_template("503.html"), 503

    @app.errorhandler(404)
    @app.errorhandler(StoreApiResourceNotFound)
    def handle_resource_not_found(error):
        return render_template("404.html", message=str(error)), 404

    @app.errorhandler(ApiTimeoutError)
    @app.errorhandler(StoreApiTimeoutError)
    def handle_connection_timeout(error):
        status_code = 504
        return (
            render_template(
                "50X.html", error_message=str(error), status_code=status_code
            ),
            status_code,
        )

    @app.errorhandler(ApiResponseDecodeError)
    @app.errorhandler(ApiResponseError)
    @app.errorhandler(ApiConnectionError)
    @app.errorhandler(StoreApiResponseDecodeError)
    @app.errorhandler(StoreApiResponseError)
    @app.errorhandler(StoreApiConnectionError)
    @app.errorhandler(ApiError)
    @app.errorhandler(StoreApiError)
    def store_api_error(error):
        status_code = 502
        return (
            render_template(
                "50X.html", error_message=str(error), status_code=status_code
            ),
            status_code,
        )

    @app.errorhandler(ApiResponseErrorList)
    @app.errorhandler(StoreApiResponseErrorList)
    def handle_api_error_list(error):
        if error.status_code == 404:
            if "snap_name" in request.path:
                return flask.abort(404, "Snap not found!")
            else:
                return (
                    render_template("404.html", message="Entity not found"),
                    404,
                )
        if len(error.errors) == 1 and error.errors[0]["code"] in [
            "macaroon-permission-required",
            "macaroon-authorization-required",
        ]:
            authentication.empty_session(flask.session)
            return flask.redirect(f"/login?next={flask.request.path}")

        status_code = 502
        codes = [
            f"{error['code']}: {error.get('message', 'No message')}"
            for error in error.errors
        ]

        error_msg = ", ".join(codes)
        return (
            render_template(
                "50X.html", error_message=error_msg, status_code=status_code
            ),
            status_code,
        )

    # Publisher error
    @app.errorhandler(PublisherMissingUsername)
    def handle_publisher_missing_name(error):
        return flask.redirect(flask.url_for("account.get_account_name"))

    @app.errorhandler(PublisherAgreementNotSigned)
    def handle_publisher_agreement_not_signed(error):
        return flask.redirect(flask.url_for("account.get_agreement"))

    @app.errorhandler(PublisherMacaroonRefreshRequired)
    def handle_publisher_macaroon_refresh_required(error):
        return refresh_redirect(flask.request.path)

    # Global tasks for all requests
    # ===
    @app.before_request
    def clear_trailing():
        """
        Remove trailing slashes from all routes
        We like our URLs without slashes
        """

        parsed_url = urlparse(unquote(flask.request.url))
        path = parsed_url.path

        if path != "/" and path.endswith("/"):
            new_uri = urlunparse(parsed_url._replace(path=path[:-1]))

            return flask.redirect(new_uri)

    @app.before_request
    def prometheus_metrics():
        # Accept-encoding counter
        # ===
        agent_string = flask.request.headers.get("User-Agent")

        # Exclude probes, which happen behind the cache
        if agent_string and not agent_string.startswith(
            ("kube-probe", "Prometheus")
        ):
            agent = user_agents.parse(agent_string or "")

            accept_encoding_counter.labels(
                accept_encoding=flask.request.headers.get("Accept-Encoding"),
                browser_family=agent.browser.family,
            ).inc()

        # Badge counters
        # ===
        if "/static/images/badges" in flask.request.url:
            if flask.session:
                badge_logged_in_counter.inc()
            else:
                badge_counter.inc()

    # Calculate the SHA256 hash of the script content and encode it in base64.
    def calculate_sha256_base64(script_content):
        sha256_hash = hashlib.sha256(script_content.encode()).digest()
        return "sha256-" + base64.b64encode(sha256_hash).decode()

    def get_csp_directive(content, regex):
        directive_items = set()
        pattern = re.compile(regex)
        matched_contents = pattern.findall(content)
        for matched_content in matched_contents:
            hash_value = f"'{calculate_sha256_base64(matched_content)}'"
            directive_items.add(hash_value)
        return list(directive_items)

    # Find all script elements in the response and add their hashes to the CSP.
    def add_script_hashes_to_csp(response):
        response.freeze()
        decoded_content = b"".join(response.response).decode(
            "utf-8", errors="replace"
        )

        CSP["script-src"] = CSP_SCRIPT_SRC + get_csp_directive(
            decoded_content, r'onclick\s*=\s*"(.*?)"'
        )
        return CSP

    @app.after_request
    def add_headers(response):
        """
        Generic rules for headers to add to all requests

        - X-Hostname: Mention the name of the host/pod running the application
        - Cache-Control: Add cache-control headers for public and private pages
        - Content-Security-Policy: Restrict resources (e.g., JavaScript, CSS,
        Images) and URLs
        - Referrer-Policy: Limit referrer data for security while preserving
        full referrer for same-origin requests
        - Cross-Origin-Embedder-Policy: allows embedding cross-origin
        resources
        - Cross-Origin-Opener-Policy: enable the page to open pop-ups while
        maintaining same-origin policy
        - Cross-Origin-Resource-Policy: allowing cross-origin requests to
        access the resource
        - X-Permitted-Cross-Domain-Policies: disallows cross-domain access to
        resources
        """

        response.headers["X-Hostname"] = socket.gethostname()

        if response.status_code == 200:
            if flask.session:
                response.headers["Cache-Control"] = "private"
            else:
                # Only add caching headers to successful responses
                if not response.headers.get("Cache-Control"):
                    response.headers["Cache-Control"] = ", ".join(
                        {
                            "public",
                            "max-age=61",
                            "stale-while-revalidate=300",
                            "stale-if-error=86400",
                        }
                    )
        csp = add_script_hashes_to_csp(response)
        response.headers["Content-Security-Policy"] = helpers.get_csp_as_str(
            csp
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Embedder-Policy"] = "unsafe-none"
        response.headers["Cross-Origin-Opener-Policy"] = (
            "same-origin-allow-popups"
        )
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        return response
