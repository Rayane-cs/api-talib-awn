<?php
function ok($data = null) {
    echo json_encode(['ok' => true, 'data' => $data]);
    exit;
}
function err($msg, $code = 400) {
    http_response_code($code);
    echo json_encode(['ok' => false, 'error' => $msg]);
    exit;
}