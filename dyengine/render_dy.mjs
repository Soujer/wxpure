// 抖音码「官方样式」渲染入口：由 Python 侧调用
// 用法： node render_dy.mjs '<json>' <out.png>
// json: {"data","size","dark","transparent","frame","badge","logo",
//        "centerImage","badgeImage","moduleStyle"}
import { readFileSync, writeFileSync } from 'node:fs'
import { generateDy } from '@ikenxuan/qrcode'

const [rawJson, outPath] = process.argv.slice(2)
if (!rawJson || !outPath) {
  console.error('usage: node render_dy.mjs <json> <out.png>')
  process.exit(2)
}

let o = {}
try {
  o = JSON.parse(rawJson)
} catch (e) {
  console.error('bad json: ' + e.message)
  process.exit(2)
}

const opt = {
  data: String(o.data ?? ''),
  size: Number(o.size ?? 600),
  darkColor: o.dark || '#161823',
  transparent: !!o.transparent,
  frame: o.frame !== false,
  badge: o.badge !== false,
  logo: o.logo !== false,
  moduleStyle: o.moduleStyle || 'rounded',
}
if (o.centerImage) opt.centerImage = readFileSync(o.centerImage)
if (o.badgeImage) opt.badgeImage = readFileSync(o.badgeImage)

const png = await generateDy(opt, 'png')
writeFileSync(outPath, png)
console.log('ok ' + outPath + ' ' + png.length)
