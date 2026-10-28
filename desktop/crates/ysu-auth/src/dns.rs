//! DNS failure changes only the connection address, never the URL/TLS identity.
//! Decision: .agents/notes/implemented/desktop/2026-10-28-campus-ip-fallback.md
use reqwest::dns::{Addrs, Name, Resolve, Resolving};
use std::{
    future::Future,
    io,
    net::{IpAddr, SocketAddr},
    time::Duration,
};

const ADDRESSES: &str = include_str!("../../../../src/ysu_net/auth/campus-addresses.json");
// Passive status observations have a two-second total deadline. Leave most of
// that budget for TLS and the portal requests when system DNS stalls.
const LOOKUP_BUDGET: Duration = Duration::from_millis(500);

pub(crate) struct CampusResolver;

fn fallback_ip(host: &str) -> Option<IpAddr> {
    let data: serde_json::Value = serde_json::from_str(ADDRESSES).ok()?;
    if data["version"] != 1 {
        return None;
    }
    data["addresses"][host].as_str()?.parse().ok()
}

async fn choose_addresses<F>(
    fallback: Option<IpAddr>,
    lookup: F,
    budget: Duration,
) -> io::Result<Vec<SocketAddr>>
where
    F: Future<Output = io::Result<Vec<SocketAddr>>>,
{
    let Some(ip) = fallback else {
        // Custom endpoints keep their normal resolver and connection budget.
        return lookup.await;
    };
    match tokio::time::timeout(budget, lookup).await {
        Ok(Ok(addresses)) if !addresses.is_empty() => Ok(addresses),
        // No TCP or TLS request has been made when DNS fails. This is not an
        // HTTP retry and cannot replay a credential or state-changing body.
        _ => Ok(vec![SocketAddr::new(ip, 0)]),
    }
}

impl Resolve for CampusResolver {
    fn resolve(&self, name: Name) -> Resolving {
        let host = name.as_str().to_owned();
        Box::pin(async move {
            let lookup = async {
                tokio::net::lookup_host((host.as_str(), 0))
                    .await
                    .map(|addresses| addresses.collect())
            };
            let addresses = choose_addresses(fallback_ip(&host), lookup, LOOKUP_BUDGET).await?;
            Ok(Box::new(addresses.into_iter()) as Addrs)
        })
    }
}

#[cfg(test)]
#[path = "dns_tests.rs"]
mod tests;
