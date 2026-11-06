#![allow(dead_code)] // wired into the CAS flow in the following change

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
        let charset: Vec<String> = serde_json::from_str(CHARSET_JSON)
            .map_err(|_| AuthError::query("验证码字符集损坏"))?;
        let model = tract_onnx::onnx()
            .model_for_path(model)
            .and_then(|m| m.with_input_names(["input1"]))
            .and_then(|m| m.into_optimized())
            .and_then(|m| m.into_runnable())
            .map_err(|_| {
                AuthError::query("验证码模型加载失败").because(Reason::ResponseInvalid)
            })?;
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
        let flat = logits.as_slice().ok_or_else(|| AuthError::query("验证码推理输出异常"))?;
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
        let decoded = image::load_from_memory(image)
            .map_err(|_| AuthError::query("验证码图片无法解码"))?;
        let gray = decoded.to_luma8();
        let (width, height) = gray.dimensions();
        if width == 0 || height == 0 {
            return Err(AuthError::query("验证码图片为空"));
        }
        let target_width = ((width as f32 * TARGET_HEIGHT as f32) / height as f32).round().max(1.0) as u32;
        let scaled = image::imageops::resize(&gray, target_width, TARGET_HEIGHT, image::imageops::FilterType::Triangle);
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
