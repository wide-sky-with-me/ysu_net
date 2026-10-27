//! Navigation rejection evidence contains only closed categories, never URL material.
//! Classification is not permission to navigate, upgrade, submit or authenticate.
//! Decision: .agents/notes/implemented/desktop/2026-10-27-portal-entry-variants.md
use serde::Serialize;
use url::Url;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NavigationKind {
    #[default]
    HttpLocation,
    HtmlNavigation,
    BrowserDocument,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Scheme {
    Http,
    Https,
    #[default]
    Other,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Role {
    Portal,
    Cas,
    Captive,
    #[default]
    Other,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Route {
    Root,
    Index,
    Redirect,
    PortalMain,
    CasLogin,
    #[default]
    Other,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Query {
    #[default]
    None,
    ExactHistory,
    Other,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Port {
    Default,
    #[default]
    Other,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Sid {
    #[default]
    Absent,
    OneValid,
    Multiple,
    Invalid,
    FlowOnly,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Method {
    Get,
    #[default]
    Other,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
struct Endpoint {
    scheme: Scheme,
    role: Role,
    host_role: Role,
    route: Route,
    query: Query,
    port: Port,
    userinfo: bool,
    fragment: bool,
    sid: Sid,
}

impl Endpoint {
    fn capture(url: &Url, portal: &Url, cas: &Url) -> Self {
        let scheme = match url.scheme() {
            "http" => Scheme::Http,
            "https" => Scheme::Https,
            _ => Scheme::Other,
        };
        // Roles compare full configured origins, not look-alike hosts or path suffixes.
        // A legacy HTTP URL on the portal host is still a different origin.
        let role = if url.origin() == portal.origin() {
            Role::Portal
        } else if url.origin() == cas.origin() {
            Role::Cas
        } else if url.scheme() == "https"
            && url.host_str() == Some("124.124.124.124")
            && url.port_or_known_default() == Some(443)
        {
            Role::Captive
        } else {
            Role::Other
        };
        // Host equality is separate evidence: legacy HTTP on the portal host differs
        // from an outside HTTP host, even though both fail strict origin matching.
        // Neither diagnostic role is an authorization decision.
        let host_role = if url.host().is_some() && url.host() == portal.host() {
            Role::Portal
        } else if url.host().is_some() && url.host() == cas.host() {
            Role::Cas
        } else if url.host_str() == Some("124.124.124.124") {
            Role::Captive
        } else {
            Role::Other
        };
        let route = match url.path() {
            "" | "/" => Route::Root,
            "/eportal/index.jsp" => Route::Index,
            "/eportal/redirect.jsp" => Route::Redirect,
            "/portal/portal-main" => Route::PortalMain,
            "/authserver/login" => Route::CasLogin,
            _ => Route::Other,
        };
        let query = match url.query() {
            None => Query::None,
            Some("mode=history") => Query::ExactHistory,
            Some(_) => Query::Other,
        };
        let port = match (url.scheme(), url.port_or_known_default()) {
            ("http", Some(80)) | ("https", Some(443)) => Port::Default,
            _ => Port::Other,
        };
        Self {
            scheme,
            role,
            host_role,
            route,
            query,
            port,
            userinfo: !url.username().is_empty() || url.password().is_some(),
            fragment: url.fragment().is_some(),
            sid: sid_shape(url),
        }
    }

    fn detail(self, prefix: &'static str) -> String {
        format!(
            "{prefix}_scheme={} {prefix}_role={} {prefix}_host_role={} \
             {prefix}_route={} {prefix}_query={} \
             {prefix}_port={} {prefix}_userinfo={} {prefix}_fragment={} {prefix}_sid={}",
            token(self.scheme),
            token(self.role),
            token(self.host_role),
            token(self.route),
            token(self.query),
            token(self.port),
            self.userinfo,
            self.fragment,
            token(self.sid),
        )
    }
}

fn sid_shape(url: &Url) -> Sid {
    let mut sessions = 0u8;
    let mut flows = 0u8;
    let mut valid = true;
    for (key, value) in url.query_pairs() {
        if key == "sessionId" || key == "flowSessionId" {
            if key == "sessionId" {
                sessions = sessions.saturating_add(1);
            } else {
                flows = flows.saturating_add(1);
            }
            valid &=
                !value.is_empty() && value.len() <= 1024 && !value.chars().any(char::is_control);
        }
    }
    if sessions.saturating_add(flows) > 1 {
        Sid::Multiple
    } else if sessions == 0 && flows == 0 {
        Sid::Absent
    } else if !valid {
        Sid::Invalid
    } else if sessions == 1 {
        Sid::OneValid
    } else {
        Sid::FlowOnly
    }
}

// Every caller supplies an enum declared in this module; arbitrary strings are never stored.
fn token(value: impl Serialize) -> String {
    serde_json::to_value(value)
        .expect("fixed navigation category")
        .as_str()
        .expect("navigation category is a fixed token")
        .to_owned()
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
pub struct NavigationDiagnostic {
    kind: NavigationKind,
    source: Endpoint,
    target: Endpoint,
    method: Method,
    has_body: bool,
}

impl NavigationDiagnostic {
    pub(crate) fn capture(
        kind: NavigationKind,
        source: &Url,
        target: &Url,
        portal: &Url,
        cas: &Url,
        method: &str,
        has_body: bool,
    ) -> Self {
        Self {
            kind,
            source: Endpoint::capture(source, portal, cas),
            target: Endpoint::capture(target, portal, cas),
            method: if method == "GET" {
                Method::Get
            } else {
                Method::Other
            },
            has_body,
        }
    }

    /// Return fixed key/token pairs only; no host, URL, path, query value or error text.
    pub fn detail(&self) -> String {
        format!(
            "nav_kind={} nav_method={} nav_body={} {} {}",
            token(self.kind),
            token(self.method),
            self.has_body,
            self.source.detail("nav_source"),
            self.target.detail("nav_target"),
        )
    }
}
