<?php
$user = requireAuth($pdo);

if ($method === 'GET' && strpos($uri, '/notifications') !== false) {
    $stmt = $pdo->prepare("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 50");
    $stmt->execute([$user['id']]);
    ok($stmt->fetchAll());
}

if ($method === 'POST' && strpos($uri, '/notifications') !== false) {
    $title = $body['title'] ?? '';
    if (!$title) err('title required');

    $pdo->prepare(
        "INSERT INTO notifications (user_id,title,body,type) VALUES (?,?,?,?)"
    )->execute([
        $user['id'],
        $title,
        $body['body'] ?? null,
        $body['type'] ?? 'info'
    ]);

    ok(['created'=>true]);
}