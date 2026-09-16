/*
 * 头像：选一张图 → 缩到 96×96 → 重新编码成 data URL → 存 per-user prefs。
 *
 * 没有上传接口，也没有静态文件卷。理由是这张图跟语言、默认索引是同一类东西
 * （这个账号自己的偏好），prefs 那条路已经在做跨设备同步，再开一条上传 + 存储
 * + 回源的链路只是为了同一件事多三个失败点。
 *
 * 「重新编码」是这里唯一的安全措施，也是够用的那个：进来的字节从不原样存下去，
 * 而是解码成位图、画进 canvas、再由浏览器编码出来。EXIF、附在图片尾部的载荷、
 * 伪装成 png 的东西，都在这一步消失。SVG 单独拒掉 —— 它是能带脚本的文档格式，
 * 不是位图，让它走到 <img> 的 src 上没有任何好处。
 */

/** 存进 prefs 的边长。96 是顶栏 28px 头像在 3× 屏上的清晰度。 */
const SIZE = 96

/** data URL 的字节上限。96×96 的 webp 通常 3–8KB，留足余量仍远小于 prefs 文档。 */
const MAX_BYTES = 64 * 1024

export const ACCEPT = 'image/png,image/jpeg,image/webp,image/gif,image/bmp'

export class AvatarError extends Error {}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new AvatarError('decode'))
    }
    img.src = url
  })
}

/**
 * 把用户选的文件变成一张 96×96 的 data URL。
 *
 * 抛 AvatarError 的三种情况：不是位图、解不开、编完还是太大。调用方负责把它
 * 翻译成人话 —— 这个模块不认识文案表。
 */
export async function fileToAvatar(file: File): Promise<string> {
  if (!file.type.startsWith('image/') || file.type === 'image/svg+xml') {
    throw new AvatarError('type')
  }
  const img = await loadImage(file)

  const canvas = document.createElement('canvas')
  canvas.width = SIZE
  canvas.height = SIZE
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new AvatarError('canvas')

  // 按短边裁成正方形再缩放（cover），否则非正方形的图会被压扁。
  const side = Math.min(img.naturalWidth, img.naturalHeight)
  const sx = (img.naturalWidth - side) / 2
  const sy = (img.naturalHeight - side) / 2
  ctx.drawImage(img, sx, sy, side, side, 0, 0, SIZE, SIZE)

  // webp 体积小一半；老浏览器不认就退回 png（toDataURL 认不出格式时会回 png，
  // 所以这里靠前缀判断而不是相信参数）。
  let url = canvas.toDataURL('image/webp', 0.85)
  if (!url.startsWith('data:image/webp')) url = canvas.toDataURL('image/png')

  if (url.length > MAX_BYTES) throw new AvatarError('size')
  return url
}
