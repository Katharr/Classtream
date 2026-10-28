// Translate only known server error codes; preserve student-authored content.
export function explainError(reason, fallback) {
  const messages = {
    'Invalid credentials':'账号或密码不正确，请重新输入',
    'Unauthorized':'登录已失效，请刷新页面后重新登录',
    'File too large (max 50 MB)':'文件超过 50 MB，请压缩后再发送',
    'Empty file':'文件为空，请选择其他文件',
    'name cannot be empty':'请输入姓名',
  };
  return messages[reason] || (reason?.startsWith('File type ') ? '暂不支持此文件格式，请打包为 ZIP 后发送' : fallback);
}
