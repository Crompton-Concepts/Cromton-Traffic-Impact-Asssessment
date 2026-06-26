const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execSync } = require('child_process');

/**
 * build-prod.js — Production build with cache-busting and inline options.
 *
 * Steps:
 * 1. Run TypeScript type check (tsc --noEmit)
 * 2. Build bundle with esbuild JS API (with content hash)
 * 3. Update index.html to reference hashed bundle
 * 4. Optionally produce an inline CSP-friendly build
 *
 * Usage: node build-prod.js [--inline]
 */

const DIST_DIR = path.resolve(__dirname, 'dist');
const SRC_ENTRY = path.resolve(__dirname, 'src', 'index.ts');
const INDEX_HTML = path.resolve(__dirname, 'index.html');

function hashContent(content) {
  return crypto.createHash('sha256').update(content).digest('hex').slice(0, 12);
}

function cleanOldBundles() {
  if (!fs.existsSync(DIST_DIR)) return;
  const files = fs.readdirSync(DIST_DIR);
  for (const file of files) {
    if (file.startsWith('tia-bundle.') && file.endsWith('.js')) {
      fs.unlinkSync(path.join(DIST_DIR, file));
      console.log(`  Cleaned old: ${file}`);
    }
  }
}

async function buildBundle() {
  console.log('Step 1: Type check...');
  execSync('node node_modules/typescript/bin/tsc --noEmit', {
    cwd: __dirname,
    stdio: 'inherit',
  });

  console.log('\nStep 2: Build bundle...');
  cleanOldBundles();

  const tempBundle = path.join(DIST_DIR, 'tia-bundle-temp.js');
  // Use esbuild JavaScript API instead of shell to avoid path-space issues
  const esbuild = require('esbuild');
  await esbuild.build({
    entryPoints: [SRC_ENTRY],
    bundle: true,
    outfile: tempBundle,
    format: 'iife',
    globalName: 'TIA',
    minify: true,
    sourcemap: true,
    target: 'es2020',
    platform: 'browser',
  });

  const bundleContent = fs.readFileSync(tempBundle);
  const hash = hashContent(bundleContent);
  const hashedName = `tia-bundle.${hash}.js`;
  const hashedPath = path.join(DIST_DIR, hashedName);

  fs.renameSync(tempBundle, hashedPath);

  // Also rename the source map if it exists
  const tempMap = tempBundle + '.map';
  if (fs.existsSync(tempMap)) {
    fs.renameSync(tempMap, hashedPath + '.map');
  }

  console.log(`  Built: ${hashedName} (${(bundleContent.length / 1024).toFixed(1)} KB)`);
  return { hash, hashedName, hashedPath };
}

function updateIndexHtml(hashedName) {
  console.log('\nStep 3: Update index.html...');
  let html = fs.readFileSync(INDEX_HTML, 'utf-8');

  // Replace any existing tia-bundle.js reference with hashed version
  html = html.replace(
    /src="dist\/tia-bundle[^"]*\.js"/,
    `src="dist/${hashedName}"`
  );

  // Update CSS cache-busting query string
  const cssHash = hashContent(fs.readFileSync(path.resolve(__dirname, 'styles.css')));
  html = html.replace(
    /href="styles\.css\?v=[^"]*"/,
    `href="styles.css?v=${cssHash}"`
  );

  fs.writeFileSync(INDEX_HTML, html, 'utf-8');
  console.log(`  Updated index.html -> ${hashedName}`);
  console.log(`  Updated styles.css?v=${cssHash}`);
}

function buildInline() {
  console.log('\nStep 4: Inline CSP build...');
  const inlineScript = path.resolve(__dirname, 'build-inline.js');
  execSync(
    `node "${inlineScript}" index.html dist/index-inline.html`,
    { cwd: __dirname, stdio: 'inherit' }
  );
}

// ── Main ───────────────────────────────────────────────────────────

const doInline = process.argv.includes('--inline');

(async () => {
  try {
    const { hashedName } = await buildBundle();
    updateIndexHtml(hashedName);
    if (doInline) {
      buildInline();
    }
    console.log('\n✅ Production build complete.');
    console.log(`   Bundle: dist/${hashedName}`);
    if (doInline) {
      console.log('   Inline: dist/index-inline.html');
    }
  } catch (err) {
    console.error('\n❌ Build failed:', err.message);
    process.exit(1);
  }
})();
