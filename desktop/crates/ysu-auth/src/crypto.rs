use crate::AuthError;
use aes::cipher::{block_padding::Pkcs7, BlockEncryptMut, KeyIvInit};
use base64::{engine::general_purpose::STANDARD, Engine};
use rand::{rngs::OsRng, Rng};
use zeroize::Zeroizing;

const CHARS: &[u8] = b"ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678";

pub(crate) fn encrypt_password(password: &str, salt: &str) -> Result<String, AuthError> {
    let mut rng = OsRng;
    let prefix: Vec<u8> = (0..64)
        .map(|_| CHARS[rng.gen_range(0..CHARS.len())])
        .collect();
    let iv: Vec<u8> = (0..16)
        .map(|_| CHARS[rng.gen_range(0..CHARS.len())])
        .collect();
    encrypt_with_material(password, salt.trim().as_bytes(), &prefix, &iv)
}

pub(crate) fn encrypt_with_material(
    password: &str,
    key: &[u8],
    prefix: &[u8],
    iv: &[u8],
) -> Result<String, AuthError> {
    if prefix.len() != 64 || iv.len() != 16 {
        return Err(AuthError::query("统一认证加密参数异常"));
    }
    let mut plain = Zeroizing::new(prefix.to_vec());
    plain.extend_from_slice(password.as_bytes());
    let invalid = || AuthError::interaction("统一认证加密参数异常，请检查门户页面或风控状态");
    let encrypted = match key.len() {
        16 => cbc::Encryptor::<aes::Aes128>::new_from_slices(key, iv)
            .map_err(|_| invalid())?
            .encrypt_padded_vec_mut::<Pkcs7>(&plain),
        24 => cbc::Encryptor::<aes::Aes192>::new_from_slices(key, iv)
            .map_err(|_| invalid())?
            .encrypt_padded_vec_mut::<Pkcs7>(&plain),
        32 => cbc::Encryptor::<aes::Aes256>::new_from_slices(key, iv)
            .map_err(|_| invalid())?
            .encrypt_padded_vec_mut::<Pkcs7>(&plain),
        _ => return Err(invalid()),
    };
    Ok(STANDARD.encode(encrypted))
}
