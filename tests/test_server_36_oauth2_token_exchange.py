import json
import os

import pytest
from cryptojwt.jwt import utc_time_sans_frac
from cryptojwt.key_jar import build_keyjar

from idpyoidc.message.oauth2 import TokenExchangeRequest
from idpyoidc.message.oidc import AccessTokenRequest
from idpyoidc.message.oidc import AuthorizationRequest
from idpyoidc.message.oidc import RefreshAccessTokenRequest
from idpyoidc.server import Server
from idpyoidc.server.authn_event import create_authn_event
from idpyoidc.server.authz import AuthzHandling
from idpyoidc.server.client_authn import verify_client
from idpyoidc.server.configure import ASConfiguration
from idpyoidc.server.cookie_handler import CookieHandler
from idpyoidc.server.user_authn.authn_context import INTERNETPROTOCOLPASSWORD
from idpyoidc.server.user_info import UserInfo

KEYDEFS = [
    {"type": "RSA", "key": "", "use": ["sig"]},
    {"type": "EC", "crv": "P-256", "use": ["sig"]},
]

CLIENT_KEYJAR = build_keyjar(KEYDEFS)

COOKIE_KEYDEFS = [
    {"type": "oct", "kid": "sig", "use": ["sig"]},
    {"type": "oct", "kid": "enc", "use": ["enc"]},
]

RESPONSE_TYPES_SUPPORTED = [
    ["code"],
    ["token"],
    ["id_token"],
    ["code", "token"],
    ["code", "id_token"],
    ["id_token", "token"],
    ["code", "token", "id_token"],
    ["none"],
]

CAPABILITIES = {
    "subject_types_supported": ["public", "pairwise", "ephemeral"],
    "grant_types_supported": [
        "authorization_code",
        "implicit",
        "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "refresh_token",
    ],
}

AUTH_REQ = AuthorizationRequest(
    client_id="client_1",
    redirect_uri="https://example.com/cb",
    scope=["openid"],
    state="STATE",
    response_type="code",
)

TOKEN_REQ = AccessTokenRequest(
    client_id="client_1",
    redirect_uri="https://example.com/cb",
    state="STATE",
    grant_type="authorization_code",
    client_secret="hemligt",
)

REFRESH_TOKEN_REQ = RefreshAccessTokenRequest(
    grant_type="refresh_token", client_id="https://example.com/", client_secret="hemligt"
)

TOKEN_REQ_DICT = TOKEN_REQ.to_dict()

BASEDIR = os.path.abspath(os.path.dirname(__file__))


def full_path(local_file):
    return os.path.join(BASEDIR, local_file)


USERINFO = UserInfo(json.loads(open(full_path("users.json")).read()))


class TestEndpoint(object):
    @pytest.fixture(autouse=True)
    def create_endpoint(self):
        conf = {
            "issuer": "https://example.com/",
            "httpc_params": {"verify": False, "timeout": 1},
            "capabilities": CAPABILITIES,
            "cookie_handler": {
                "class": CookieHandler,
                "kwargs": {"keys": {"key_defs": COOKIE_KEYDEFS}},
            },
            "keys": {"uri_path": "jwks.json", "key_defs": KEYDEFS},
            "endpoint": {
                "authorization": {
                    "path": "authorization",
                    "class": 'idpyoidc.server.oauth2.authorization.Authorization',
                    "kwargs": {},
                },
                "token": {
                    "path": "token",
                    "class": "idpyoidc.server.oidc.token.Token",
                    "kwargs": {
                        "client_authn_method": [
                            "client_secret_basic",
                            "client_secret_post",
                            "client_secret_jwt",
                            "private_key_jwt",
                        ],
                    },
                },
                "introspection": {
                    "path": "introspection",
                    "class": "idpyoidc.server.oauth2.introspection.Introspection",
                    "kwargs": {},
                },
            },
            "authentication": {
                "anon": {
                    "acr": INTERNETPROTOCOLPASSWORD,
                    "class": "idpyoidc.server.user_authn.user.NoAuthn",
                    "kwargs": {"user": "diana"},
                }
            },
            "userinfo": {"class": UserInfo, "kwargs": {"db": {}}},
            "client_authn": verify_client,
            "template_dir": "template",
            "authz": {
                "class": AuthzHandling,
                "kwargs": {
                    "grant_config": {
                        "usage_rules": {
                            "authorization_code": {
                                "supports_minting": ["access_token", "refresh_token"],
                                "max_usage": 1,
                            },
                            "access_token": {
                                "supports_minting": ["access_token", "refresh_token"],
                                "expires_in": 600,
                            },
                            "refresh_token": {
                                "supports_minting": ["access_token", "refresh_token"],
                                "audience": ["https://example.com", "https://example2.com"],
                                "expires_in": 43200,
                            },
                        },
                        "expires_in": 43200,
                    }
                },
            },
            "token_handler_args": {
                "jwks_file": "private/token_jwks.json",
                "code": {"kwargs": {"lifetime": 600}},
                "token": {
                    "class": "idpyoidc.server.token.jwt_token.JWTToken",
                    "kwargs": {
                        "lifetime": 3600,
                        "add_claims_by_scope": True,
                        "aud": ["https://example.org/appl"],
                    },
                },
                "refresh": {
                    "class": "idpyoidc.server.token.jwt_token.JWTToken",
                    "kwargs": {"lifetime": 3600, "aud": ["https://example.org/appl"], },
                },
            },
        }
        server = Server(ASConfiguration(conf=conf, base_path=BASEDIR), cwd=BASEDIR)
        self.endpoint_context = server.endpoint_context
        self.endpoint_context.cdb["client_1"] = {
            "client_secret": "hemligt",
            "redirect_uris": [("https://example.com/cb", None)],
            "client_salt": "salted",
            "token_endpoint_auth_method": "client_secret_post",
            "response_types": ["code", "token", "code id_token", "id_token"],
            "allowed_scopes": ["openid", "profile", "offline_access"],
        }
        self.endpoint_context.cdb["client_2"] = {
            "client_secret": "hemligt",
            "redirect_uris": [("https://example.com/cb", None)],
            "client_salt": "salted",
            "token_endpoint_auth_method": "client_secret_post",
            "response_types": ["code", "token", "code id_token", "id_token"],
            "allowed_scopes": ["openid", "profile", "offline_access"],
        }
        self.endpoint_context.keyjar.import_jwks(CLIENT_KEYJAR.export_jwks(), "client_1")
        self.endpoint = server.server_get("endpoint", "token")
        self.introspection_endpoint = server.server_get("endpoint", "introspection")
        self.session_manager = self.endpoint_context.session_manager
        self.user_id = "diana"

    def _create_session(self, auth_req, sub_type="public", sector_identifier=""):
        if sector_identifier:
            authz_req = auth_req.copy()
            authz_req["sector_identifier_uri"] = sector_identifier
        else:
            authz_req = auth_req
        client_id = authz_req["client_id"]
        ae = create_authn_event(self.user_id)
        return self.session_manager.create_session(
            ae, authz_req, self.user_id, client_id=client_id, sub_type=sub_type
        )

    def _mint_code(self, grant, client_id):
        session_id = self.session_manager.encrypted_session_id(self.user_id, client_id, grant.id)
        usage_rules = grant.usage_rules.get("authorization_code", {})
        _exp_in = usage_rules.get("expires_in")

        # Constructing an authorization code is now done
        _code = grant.mint_token(
            session_id=session_id,
            endpoint_context=self.endpoint.server_get("endpoint_context"),
            token_class="authorization_code",
            token_handler=self.session_manager.token_handler["authorization_code"],
            usage_rules=usage_rules,
        )

        if _exp_in:
            if isinstance(_exp_in, str):
                _exp_in = int(_exp_in)
            if _exp_in:
                _code.expires_at = utc_time_sans_frac() + _exp_in
        return _code

    @pytest.mark.parametrize(
        "token",
        [
            {"access_token": "urn:ietf:params:oauth:token-type:access_token"},
            {"refresh_token": "urn:ietf:params:oauth:token-type:refresh_token"},
        ],
    )
    def test_token_exchange(self, token):
        """
        Test that token exchange requests work correctly
        """
        if list(token.keys())[0] == "refresh_token":
            AUTH_REQ["scope"] = ["openid", "offline_access"]
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)
        _token_value = _resp["response_args"][list(token.keys())[0]]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type=token[list(token.keys())[0]],
            requested_token_type=token[list(token.keys())[0]],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzI6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp["response_args"].keys()) == {
            "access_token",
            "token_type",
            "scope",
            "expires_in",
            "issued_token_type",
        }

    @pytest.mark.parametrize(
        "token",
        [
            {"access_token": "urn:ietf:params:oauth:token-type:access_token"},
            {"refresh_token": "urn:ietf:params:oauth:token-type:refresh_token"},
        ],
    )
    def test_token_exchange_per_client(self, token):
        """
        Test that per-client token exchange configuration works correctly
        """
        self.endpoint_context.cdb["client_1"]["token_exchange"] = {
            "subject_token_types_supported": [
                "urn:ietf:params:oauth:token-type:access_token",
                "urn:ietf:params:oauth:token-type:refresh_token",
            ],
            "requested_token_types_supported": [
                "urn:ietf:params:oauth:token-type:access_token",
                "urn:ietf:params:oauth:token-type:refresh_token",
            ],
            "policy": {
                "": {
                    "callable": "idpyoidc.server.oauth2.token_helper.validate_token_exchange_policy",
                    "kwargs": {"scope": ["openid"]},
                }
            },
        }

        if list(token.keys())[0] == "refresh_token":
            AUTH_REQ["scope"] = ["openid", "offline_access"]
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)
        _token_value = _resp["response_args"][list(token.keys())[0]]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type=token[list(token.keys())[0]],
            requested_token_type=token[list(token.keys())[0]],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp["response_args"].keys()) == {
            "access_token",
            "token_type",
            "scope",
            "expires_in",
            "issued_token_type",
        }

    def test_additional_parameters(self):
        """
        Test that a token exchange with additional parameters including
        scope, audience and subject_token_type works.
        """
        conf = self.endpoint.helper["urn:ietf:params:oauth:grant-type:token-exchange"].config
        conf["policy"][""]["kwargs"] = {}
        conf["policy"][""]["kwargs"]["audience"] = ["https://example.com"]
        conf["policy"][""]["kwargs"]["resource"] = ["https://example.com"]

        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["access_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
            requested_token_type="urn:ietf:params:oauth:token-type:access_token",
            audience=["https://example.com"],
            resource=["https://example.com"],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp["response_args"].keys()) == {
            "access_token",
            "token_type",
            "expires_in",
            "issued_token_type",
            "scope",
        }
        msg = self.endpoint.do_response(request=_req, **_resp)
        assert isinstance(msg, dict)

    def test_token_exchange_fails_if_disabled(self):
        """
        Test that token exchange fails if it's not included in Token's
        grant_types_supported (that are set in its helper attribute).
        """
        del self.endpoint.helper["urn:ietf:params:oauth:grant-type:token-exchange"]

        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["access_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
            resource=["https://example.com/api"],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert _resp["error"] == "invalid_request"
        assert (
                _resp["error_description"]
                == "Unsupported grant_type: urn:ietf:params:oauth:grant-type:token-exchange"
        )

    def test_wrong_resource(self):
        """
        Test that requesting a token for an unknown resource fails.
        """
        conf = self.endpoint.helper["urn:ietf:params:oauth:grant-type:token-exchange"].config
        conf["policy"][""]["kwargs"] = {}
        conf["policy"][""]["kwargs"]["resource"] = ["https://example.com"]
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["access_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
            resource=["https://unknown-resource.com/api"],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) == {"error", "error_description"}
        assert _resp["error"] == "invalid_target"
        assert _resp["error_description"] == "Unknown resource"

    def test_refresh_token_audience(self):
        """
        Test that requesting a refresh token with audience fails.
        """
        AUTH_REQ["scope"] = ["openid", "offline_access"]
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["refresh_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:refresh_token",
            audience=["https://example.com"],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) == {"error", "error_description"}
        assert _resp["error"] == "invalid_target"
        assert _resp["error_description"] == "Refresh token has single owner"

    def test_wrong_audience(self):
        """
        Test that requesting a token for an unknown audience fails.
        """
        conf = self.endpoint.helper["urn:ietf:params:oauth:grant-type:token-exchange"].config
        conf["policy"][""]["kwargs"] = {}
        conf["policy"][""]["kwargs"]["audience"] = ["https://example.com"]
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["access_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
            audience=["https://unknown-audience.com/"],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) == {"error", "error_description"}
        assert _resp["error"] == "invalid_target"
        assert _resp["error_description"] == "Unknown audience"

    def test_exchange_refresh_token_to_refresh_token(self):
        """
        Test whether exchanging a refresh token to another refresh token works.
        """
        AUTH_REQ["scope"] = ["openid", "offline_access"]
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])
        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["scope"] = "openid"
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["refresh_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:refresh_token",
            requested_token_type="urn:ietf:params:oauth:token-type:refresh_token",
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) != {"error", "error_description"}

    @pytest.mark.parametrize(
        "scopes",
        [
            ["openid", "offline_access"],
            ["openid"],
        ],
    )
    def test_exchange_access_token_to_refresh_token(self, scopes):
        AUTH_REQ["scope"] = scopes
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["scope"] = ["openid"]
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)
        _token_value = _resp["response_args"]["access_token"]
        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
            requested_token_type="urn:ietf:params:oauth:token-type:refresh_token",
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        if "offline_access" in scopes:
            assert set(_resp.keys()) != {"error", "error_description"}
        else:
            assert _resp["error"] == "invalid_request"

    @pytest.mark.parametrize(
        "missing_attribute",
        [
            "subject_token_type",
            "subject_token",
        ],
    )
    def test_missing_parameters(self, missing_attribute):
        """
        Test that omitting the subject_token_type fails.
        """
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["access_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
            audience=["https://example.com"],
            resource=["https://example.com/api"],
        )

        del token_exchange_req[missing_attribute]

        _req = self.endpoint.parse_request(
            # This is to get passed the deserializing which would otherwise throw an exception
            token_exchange_req,
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) == {"error", "error_description"}
        assert _resp["error"] == "invalid_request"
        assert _resp["error_description"] == f"Missing required attribute '{missing_attribute}'"

    @pytest.mark.parametrize(
        "unsupported_type",
        [
            "unknown",
            "urn:ietf:params:oauth:token-type:id_token",
            "urn:ietf:params:oauth:token-type:saml2",
            "urn:ietf:params:oauth:token-type:saml1",
        ],
    )
    def test_unsupported_requested_token_type(self, unsupported_type):
        """
        Test that requesting a token type that is unknown or unsupported fails.
        """
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["access_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
            requested_token_type=unsupported_type,
            audience=["https://example.com"],
            resource=["https://example.com/api"],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) == {"error", "error_description"}
        assert _resp["error"] == "invalid_request"
        assert _resp["error_description"] == "Unsupported requested token type"

    @pytest.mark.parametrize(
        "unsupported_type",
        [
            "unknown",
            "urn:ietf:params:oauth:token-type:id_token",
            "urn:ietf:params:oauth:token-type:saml2",
            "urn:ietf:params:oauth:token-type:saml1",
        ],
    )
    def test_unsupported_subject_token_type(self, unsupported_type):
        """
        Test that providing an unsupported subject token type fails.
        """
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["access_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type=unsupported_type,
            audience=["https://example.com"],
            resource=["https://example.com/api"],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) == {"error", "error_description"}
        assert _resp["error"] == "invalid_request"
        assert _resp["error_description"] == "Unsupported subject token type"

    def test_unsupported_actor_token(self):
        """
        Test that providing an actor token fails as it's unsupported.
        """
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        _token_value = _resp["response_args"]["access_token"]

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=_token_value,
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
            actor_token=_resp["response_args"]["access_token"],
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) == {"error", "error_description"}
        assert _resp["error"] == "invalid_request"
        assert _resp["error_description"] == "Actor token not supported"

    def test_invalid_token(self):
        """
        Test that providing an invalid token fails.
        """
        areq = AUTH_REQ.copy()

        session_id = self._create_session(areq)
        grant = self.endpoint_context.authz(session_id, areq)
        code = self._mint_code(grant, areq["client_id"])

        _token_request = TOKEN_REQ_DICT.copy()
        _token_request["code"] = code.value
        _req = self.endpoint.parse_request(_token_request)
        _resp = self.endpoint.process_request(request=_req)

        token_exchange_req = TokenExchangeRequest(
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token="invalid_token",
            subject_token_type="urn:ietf:params:oauth:token-type:access_token",
        )

        _req = self.endpoint.parse_request(
            token_exchange_req.to_urlencoded(),
            {"headers": {"authorization": "Basic {}".format("Y2xpZW50XzE6aGVtbGlndA==")}},
        )
        _resp = self.endpoint.process_request(request=_req)
        assert set(_resp.keys()) == {"error", "error_description"}
        assert _resp["error"] == "invalid_request"
        assert _resp["error_description"] == "Subject token invalid"
