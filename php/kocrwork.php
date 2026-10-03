<?php
// Kurage OCR Work (kocrwork) の公開入口（PHP だけのレンタルサーバーに置く）。
// kocrwork を動かしているサーバー :18348 への透過プロキシ。UIは相対パス(api/...)なので
// /kocrwork.php/ (末尾スラッシュ) を起点に PATH_INFO で中継する。
// バックエンドURLは同ディレクトリの kocrwork_config.php で定義する(リポジトリには含めない)
//   <?php define('KOCRWORK_BACKEND', 'http://あなたのサーバー:18348');
//   任意: define('KOCRWORK_TRACK_JS', '<script>…</script>');  … HTML の </head> 直前に差し込む計測タグ（無ければ何もしない）
$__cfg = __DIR__ . '/kocrwork_config.php';
if (is_file($__cfg)) { require_once $__cfg; }
$BACKEND = defined('KOCRWORK_BACKEND') ? KOCRWORK_BACKEND : 'http://127.0.0.1:18348';

// /kocrwork.php → /kocrwork.php/ へ(相対URL解決のため)
if (!isset($_SERVER['PATH_INFO']) || $_SERVER['PATH_INFO'] === '') {
    if (substr($_SERVER['REQUEST_URI'], -1) !== '/' && strpos($_SERVER['REQUEST_URI'], '?') === false) {
        header('Location: /kocrwork.php/', true, 302); exit;
    }
}
$path = isset($_SERVER['PATH_INFO']) ? $_SERVER['PATH_INFO'] : '/';
$qs = isset($_SERVER['QUERY_STRING']) && $_SERVER['QUERY_STRING'] !== '' ? '?' . $_SERVER['QUERY_STRING'] : '';

$ch = curl_init($BACKEND . $path . $qs);
$headers = array('X-Forwarded-Proto: https', 'X-Forwarded-Host: ' . (isset($_SERVER['HTTP_HOST']) ? $_SERVER['HTTP_HOST'] : ''));
if (!empty($_SERVER['HTTP_X_FORWARDED_FOR'])) { $headers[] = 'X-Forwarded-For: ' . $_SERVER['HTTP_X_FORWARDED_FOR']; }
elseif (!empty($_SERVER['REMOTE_ADDR'])) { $headers[] = 'X-Forwarded-For: ' . $_SERVER['REMOTE_ADDR']; }
// 受注の台帳は見る人ごとに分けている（cookie kocr_sid）。往復で cookie を中継する
if (!empty($_SERVER['HTTP_COOKIE'])) { $headers[] = 'Cookie: ' . $_SERVER['HTTP_COOKIE']; }
// CSV一括判定(multipart)は Content-Type の boundary が要る。中継しないと FastAPI が file を受け取れない
if (!empty($_SERVER['CONTENT_TYPE']) && empty($_FILES)) { $headers[] = 'Content-Type: ' . $_SERVER['CONTENT_TYPE']; }
curl_setopt_array($ch, array(
    CURLOPT_CUSTOMREQUEST => $_SERVER['REQUEST_METHOD'],
    CURLOPT_RETURNTRANSFER => true, CURLOPT_HEADER => true,
    CURLOPT_HTTPHEADER => $headers, CURLOPT_ENCODING => '',
    CURLOPT_TIMEOUT => 60, CURLOPT_FOLLOWLOCATION => false,
));
if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    if (!empty($_FILES)) {
        // multipart は php://input で読めない（PHP が $_FILES に展開してしまう）。CURLFile で組み直して送る
        $fields = $_POST;
        foreach ($_FILES as $k => $f) {
            if (isset($f['tmp_name']) && is_uploaded_file($f['tmp_name'])) {
                $fields[$k] = new CURLFile($f['tmp_name'], $f['type'] ? $f['type'] : 'application/octet-stream', $f['name']);
            }
        }
        curl_setopt($ch, CURLOPT_POSTFIELDS, $fields);
    } else {
        curl_setopt($ch, CURLOPT_POSTFIELDS, file_get_contents('php://input'));
    }
}
$res = curl_exec($ch);
if ($res === false) { http_response_code(502); header('Content-Type: text/plain; charset=utf-8');
    echo 'Kurage OCR Work のサーバーに接続できません。しばらくしてからお試しください'; exit; }
$status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$hsize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
curl_close($ch);
http_response_code($status);
foreach (explode("\r\n", substr($res, 0, $hsize)) as $h) {
    if (stripos($h, 'Content-Type:') === 0 || stripos($h, 'Cache-Control:') === 0 || stripos($h, 'Content-Disposition:') === 0) { header($h); }
    if (stripos($h, 'Set-Cookie:') === 0) { header(preg_replace('/;\s*Path=[^;]*/i', '', $h) . '; Path=/kocrwork.php/', false); }
}
// 計測タグは設定したときだけ HTML に差し込む
$body = substr($res, $hsize);
if (defined('KOCRWORK_TRACK_JS') && (stripos(implode('', headers_list()), 'text/html') !== false || stripos($body, '<!doctype html') === 0)) {
    // 再販パートナー募集の枠（中身は kurage_web/partner-bar.js。kurage.exbridge.jp 以外では何も出さない）
    $body = str_replace('</head>', KOCRWORK_TRACK_JS . '<script src="https://kurage.exbridge.jp/partner-bar.js" defer></script>' . '</head>', $body);
}
echo $body;
