//! Local captcha recognition for the CAS challenge.
//!
//! The portal captcha is an 80x30 JPEG with four alphanumeric glyphs and a
//! diagonal line. The bundled model is ddddocr's `common.onnx` (MIT), run by
//! `tract` so no native runtime ships with the app: decode, grayscale, scale to
//! height 64, normalize to [-1, 1], CNN-LSTM, greedy CTC.

use crate::{AuthError, DiagnosticReason as Reason};
use std::path::Path;
use tract_onnx::prelude::*;

const CHARSET_JSON: &str = include_str!("captcha_charset.json");
const TARGET_HEIGHT: u32 = 64;
const BLANK: usize = 0;

/// Where the opt-in model is cached; the installer never ships it.
pub fn cache_dir() -> Option<std::path::PathBuf> {
    if let Some(dir) = std::env::var_os("YSU_CAPTCHA_DIR") {
        return Some(std::path::PathBuf::from(dir));
    }
    let base = std::env::var_os("LOCALAPPDATA")
        .or_else(|| std::env::var_os("XDG_CACHE_HOME"))
        .or_else(|| std::env::var_os("HOME"))?;
    Some(
        std::path::PathBuf::from(base)
            .join("ysu-net")
            .join("captcha"),
    )
}

/// Resolves an already-available model without downloading anything.
pub fn ready_model() -> Option<std::path::PathBuf> {
    if let Some(path) = std::env::var_os("YSU_CAPTCHA_MODEL") {
        let path = std::path::PathBuf::from(path);
        return path.is_file().then_some(path);
    }
    let path = cache_dir()?.join(MODEL_FILE);
    path.is_file().then_some(path)
}

pub const MODEL_FILE: &str = "common.onnx";

/// Fixed download location; a release asset, not a product version tag.
pub const MODEL_URL: &str =
    "https://github.com/wide-sky-with-me/ysu_net/releases/download/captcha-model-v1/common.onnx";

/// What the settings page needs to render one row without touching the network.
pub struct ModelStatus {
    pub ready: bool,
    pub path: Option<std::path::PathBuf>,
    pub bytes: u64,
}

pub fn status() -> ModelStatus {
    describe(ready_model())
}

/// Split from [`status`] so the shape is testable without touching the process environment.
fn describe(path: Option<std::path::PathBuf>) -> ModelStatus {
    let bytes = path
        .as_ref()
        .and_then(|p| std::fs::metadata(p).ok())
        .map(|m| m.len())
        .unwrap_or(0);
    ModelStatus {
        ready: path.is_some(),
        path,
        bytes,
    }
}

/// Downloads from the fixed location on an explicit request.
pub async fn download() -> Result<std::path::PathBuf, AuthError> {
    let client = reqwest::Client::builder()
        .user_agent("Mozilla/5.0 YSU-Native-Auth/0.1")
        .connect_timeout(std::time::Duration::from_secs(15))
        .timeout(std::time::Duration::from_secs(300))
        .build()
        .map_err(|_| AuthError::query("验证码模型下载失败"))?;
    download_model(MODEL_URL, &client).await
}

/// SHA256 of the model this build was verified against.
pub const MODEL_SHA256: &str = "33b5cd351ee94e73a6bf8fa18c415ed8b819b3ffd342e267c30d8ad8334e34e8";

/// Downloads the model on explicit request only; a login never triggers this.
pub async fn download_model(
    url: &str,
    client: &reqwest::Client,
) -> Result<std::path::PathBuf, AuthError> {
    let dir = cache_dir().ok_or_else(|| AuthError::query("无法确定验证码模型目录"))?;
    std::fs::create_dir_all(&dir).map_err(|_| AuthError::query("无法创建验证码模型目录"))?;
    let response = client
        .get(url)
        .send()
        .await
        .map_err(|_| AuthError::query("验证码模型下载失败"))?;
    if !response.status().is_success() {
        return Err(AuthError::query("验证码模型下载失败"));
    }
    let bytes = response
        .bytes()
        .await
        .map_err(|_| AuthError::query("验证码模型下载不完整"))?;
    let digest = sha256_hex(&bytes);
    if digest != MODEL_SHA256 {
        return Err(AuthError::query("验证码模型校验失败，已丢弃"));
    }
    let target = dir.join(MODEL_FILE);
    let staging = dir.join(format!("{MODEL_FILE}.part"));
    std::fs::write(&staging, &bytes).map_err(|_| AuthError::query("验证码模型写入失败"))?;
    std::fs::rename(&staging, &target).map_err(|_| AuthError::query("验证码模型写入失败"))?;
    Ok(target)
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

pub struct CaptchaOcr {
    model: SimplePlan<TypedFact, Box<dyn TypedOp>, TypedModel>,
    charset: Vec<String>,
}

impl CaptchaOcr {
    /// Loads `common.onnx` and the matching 8210-entry charset.
    pub fn load(model: &Path) -> Result<Self, AuthError> {
        if !model.is_file() {
            return Err(AuthError::query("验证码模型文件缺失"));
        }
        let charset: Vec<String> =
            serde_json::from_str(CHARSET_JSON).map_err(|_| AuthError::query("验证码字符集损坏"))?;
        let model = tract_onnx::onnx()
            .model_for_path(model)
            .and_then(|m| m.with_input_names(["input1"]))
            .and_then(|m| m.into_optimized())
            .and_then(|m| m.into_runnable())
            .map_err(|_| AuthError::query("验证码模型加载失败").because(Reason::ResponseInvalid))?;
        Ok(Self { model, charset })
    }

    pub fn recognize(&self, image: &[u8]) -> Result<String, AuthError> {
        let tensor = self.preprocess(image)?;
        let outputs = self
            .model
            .run(tvec!(tensor.into()))
            .map_err(|_| AuthError::query("验证码推理失败").because(Reason::ResponseInvalid))?;
        let logits = outputs
            .first()
            .ok_or_else(|| AuthError::query("验证码推理无输出"))?
            .to_array_view::<f32>()
            .map_err(|_| AuthError::query("验证码推理输出异常"))?;
        let shape = logits.shape().to_vec();
        let classes = shape.last().copied().unwrap_or(0);
        if classes == 0 {
            return Err(AuthError::query("验证码推理输出异常"));
        }
        let steps = logits.len() / classes;
        let flat = logits
            .as_slice()
            .ok_or_else(|| AuthError::query("验证码推理输出异常"))?;
        let mut text = String::new();
        let mut previous = usize::MAX;
        for step in 0..steps {
            let row = &flat[step * classes..(step + 1) * classes];
            let mut best = 0usize;
            let mut best_score = f32::NEG_INFINITY;
            for (index, score) in row.iter().enumerate() {
                if *score > best_score {
                    best_score = *score;
                    best = index;
                }
            }
            if best != previous && best != BLANK {
                if let Some(ch) = self.charset.get(best) {
                    text.push_str(ch);
                }
            }
            previous = best;
        }
        Ok(text)
    }

    fn preprocess(&self, image: &[u8]) -> Result<Tensor, AuthError> {
        let decoded =
            image::load_from_memory(image).map_err(|_| AuthError::query("验证码图片无法解码"))?;
        let gray = decoded.to_luma8();
        let (width, height) = gray.dimensions();
        if width == 0 || height == 0 {
            return Err(AuthError::query("验证码图片为空"));
        }
        let target_width = ((width as f32 * TARGET_HEIGHT as f32) / height as f32)
            .round()
            .max(1.0) as u32;
        let scaled = image::imageops::resize(
            &gray,
            target_width,
            TARGET_HEIGHT,
            image::imageops::FilterType::Triangle,
        );
        let mut data = Vec::with_capacity((target_width * TARGET_HEIGHT) as usize);
        for pixel in scaled.pixels() {
            data.push((pixel[0] as f32 / 255.0 - 0.5) / 0.5);
        }
        let tensor = tract_ndarray::Array4::from_shape_vec(
            (1, 1, TARGET_HEIGHT as usize, target_width as usize),
            data,
        )
        .map_err(|_| AuthError::query("验证码张量形状异常"))?;
        Ok(tensor.into_tensor())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(name: &str) -> Option<Vec<u8>> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/captcha")
            .join(name);
        std::fs::read(path).ok()
    }
    #[test]
    fn models_hosting_url_and_digest_stay_pinned() {
        assert!(
            MODEL_URL.starts_with("https://github.com/wide-sky-with-me/ysu_net/releases/download/")
        );
        assert!(MODEL_URL.ends_with(MODEL_FILE));
        assert_eq!(MODEL_SHA256.len(), 64);
        assert!(MODEL_SHA256.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn status_reports_the_cached_file_without_downloading() {
        let dir = std::env::temp_dir().join(format!("ysu-captcha-status-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir");
        let empty = describe(None);
        assert!(!empty.ready);
        assert_eq!(empty.bytes, 0);
        assert!(empty.path.is_none());
        let model = dir.join(MODEL_FILE);
        std::fs::write(&model, b"not-a-model").expect("write fixture");
        let present = describe(Some(model.clone()));
        assert!(present.ready);
        assert_eq!(present.bytes, 11);
        assert_eq!(present.path.as_deref(), Some(model.as_path()));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn recognizes_the_observed_portal_captchas_when_a_model_is_available() {
        let Some(model) = std::env::var_os("YSU_CAPTCHA_MODEL") else {
            return;
        };
        let ocr = CaptchaOcr::load(std::path::Path::new(&model)).expect("model loads");
        for (name, expected) in [
            ("nB4f.jpg", "nb4f"),
            ("TH3C.jpg", "th3c"),
            ("HTrL.jpg", "htrl"),
        ] {
            let Some(image) = fixture(name) else { continue };
            let got = ocr.recognize(&image).expect("recognize");
            assert_eq!(
                got.to_lowercase(),
                expected,
                "{name} -> {got} (model output; case may differ from the portal)"
            );
        }
    }
}
