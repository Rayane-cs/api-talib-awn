<?php
function getBearerToken() {
    $h = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (preg_match('/Bearer\s+(.+)/i', $h, $m)) return $m[1];
    return null;
}

function requireAuth($pdo) {
    $token = getBearerToken();
    if (!$token) err('Unauthorized', 401);

    // Simple token lookup — replace with JWT if needed
    $stmt = $pdo->prepare("SELECT id, role FROM users WHERE otp = ? AND verified = 1 LIMIT 1");
    // For production: use JWT verify here
    // For simplicity: store session token in otp field after login
    $stmt->execute([$token]);
    $user = $stmt->fetch();
    if (!$user) err('Unauthorized', 401);
    return $user;
}