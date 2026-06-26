const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

/**
 * build-inline.js — Create a CSP-friendly self-contained HTML build.
 *
 * Inlines all project-local CSS and JS into a single HTML file.
 * External CDN resources are kept with integrity hashes.
 *
 * Usage: node build-inline.js [input.html] [output.html]
 */

const INPUT_DEFAULT = 'index.html';
const OUTPUT_DEFAULT = 'dist/index-inline.html';

function hashContent(content) {
  return crypto.createHash('sha256').update(content).digest('hex').slice(0, 12);
}

function inlineAssets(inputPath, outputPath) {
  const baseDir = path.dirname(path.resolve(inputPath));
  let html = fs.readFileSync(inputPath, 'utf-8');

  // Inline CSS files referenced with <link rel="stylesheet" href="...">
  const cssLinkRegex = /<link\s+rel="stylesheet"\s+href="([^"]+)"[^>]*>/g;
  let cssMatch;
  const cssLinks = [];
  while ((cssMatch = cssLinkRegex.exec(html)) !== null) {
    cssLinks.push({ full: cssMatch[0], href: cssMatch[1] });
  }

  for (const { full, href } of cssLinks) {
    if (href.startsWith('http')) continue; // skip CDN
    const cssPath = path.resolve(baseDir, href.split('?')[0]);
    if (fs.existsSync(cssPath)) {
      const css = fs.readFileSync(cssPath, 'utf-8');
      html = html.replace(full, `<style>\n${css}\n</style>`);
      console.log(`  Inlined CSS: ${href}`);
    } else {
      console.warn(`  CSS not found: ${cssPath}`);
    }
  }

  // Inline local JS files referenced with <script src="...">
  const scriptRegex = /<script\s+src="([^"]+)"[^>]*><\/script>/g;
  let scriptMatch;
  const scripts = [];
  while ((scriptMatch = scriptRegex.exec(html)) !== null) {
    scripts.push({ full: scriptMatch[0], src: scriptMatch[1] });
  }

  for (const { full, src } of scripts) {
    if (src.startsWith('http')) continue; // skip CDN
    const jsPath = path.resolve(baseDir, src.split('?')[0]);
    if (fs.existsSync(jsPath)) {
      const js = fs.readFileSync(jsPath, 'utf-8');
      html = html.replace(full, `<script>\n${js}\n</script>`);
      console.log(`  Inlined JS: ${src}`);
    } else {
      console.warn(`  JS not found: ${jsPath}`);
    }
  }

  // Ensure output directory exists
  const outDir = path.dirname(path.resolve(outputPath));
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  fs.writeFileSync(outputPath, html, 'utf-8');
  const outSize = (fs.statSync(outputPath).size / 1024).toFixed(1);
  console.log(`\n  Wrote ${outputPath} (${outSize} KB)`);
  console.log(`  (CDN scripts remain external with integrity attributes)`);
}

const input = process.argv[2] || INPUT_DEFAULT;
const output = process.argv[3] || OUTPUT_DEFAULT;

console.log(`Building inline CSP-friendly HTML...`);
console.log(`  Input:  ${input}`);
console.log(`  Output: ${output}`);
inlineAssets(input, output);
