<?php
if ($method === 'POST' && strpos($uri, '/auth/register') !== false) {
    $email    = trim($body['email'] ?? '');
    $password = $body['password'] ?? '';
    $role     = $body['role'] ?? 'student';
    if (!$email || !$password) err('Email and password required');
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) err('Invalid email');
    if (strlen($password) < 6) err('Password too short');

    $stmt = $pdo->prepare("SELECT id FROM users WHERE email = ?");
    $stmt->execute([$email]);
    if ($stmt->fetch()) err('Email already registered');

    $hash = password_hash($password, PASSWORD_BCRYPT, ['cost' => 12]);
    $otp  = str_pad(random_int(0, 999999), 6, '0', STR_PAD_LEFT);
    $exp  = date('Y-m-d H:i:s', time() + 120);

    $stmt = $pdo->prepare(
        "INSERT INTO users (email, password_hash, role, otp, otp_expires) VALUES (?,?,?,?,?)"
    );
    $stmt->execute([$email, $hash, $role, $otp, $exp]);
    $userId = $pdo->lastInsertId();

    // Auto-create profile
    if ($role === 'student') {
        $pdo->prepare("INSERT INTO student_profiles (user_id, firstname, lastname, institution, field_of_study)
                        VALUES (?,?,?,?,?)")
            ->execute([$userId,
                $body['firstname'] ?? '',
                $body['lastname'] ?? '',
                $body['institution'] ?? '',
                $body['field_of_study'] ?? ''
            ]);
    } else {
        $pdo->prepare("INSERT INTO employer_profiles (user_id, firstname, lastname, company_name, sector)
                        VALUES (?,?,?,?,?)")
            ->execute([$userId,
                $body['firstname'] ?? '',
                $body['lastname'] ?? '',
                $body['company_name'] ?? '',
                $body['domain'] ?? ''
            ]);
    }
    // Also create escrow account
    $pdo->prepare("INSERT INTO escrow_accounts (user_id) VALUES (?)")->execute([$userId]);

    // In production: email OTP. Here return it for dev.
    ok(['user_id' => $userId, 'otp' => $otp, 'message' => 'OTP sent']);
}

if ($method === 'POST' && strpos($uri, '/auth/login') !== false) {
    $email    = trim($body['email'] ?? '');
    $password = $body['password'] ?? '';
    if (!$email || !$password) err('Credentials required');

    $stmt = $pdo->prepare("SELECT * FROM users WHERE email = ?");
    $stmt->execute([$email]);
    $user = $stmt->fetch();

    if (!$user || !password_verify($password, $user['password_hash'])) err('Invalid credentials');
    if ($user['is_banned']) err('Account banned: ' . $user['ban_reason'], 403);

    // Issue simple token (use JWT in production)
    $token = bin2hex(random_bytes(32));
    $pdo->prepare("UPDATE users SET otp = ? WHERE id = ?")->execute([$token, $user['id']]);

    ok([
        'access_token' => $token,
        'user' => [
            'id'    => $user['id'],
            'email' => $user['email'],
            'role'  => $user['role']
        ]
    ]);
}