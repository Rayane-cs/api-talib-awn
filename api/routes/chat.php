<?php
$user = requireAuth($pdo);

if ($method === 'POST' && strpos($uri, '/chat/send') !== false) {
    $conv_id = $body['conversation_id'] ?? null;
    $content = trim($body['content'] ?? '');
    if (!$conv_id || !$content) err('conversation_id and content required');

    // Verify user is in conversation
    $stmt = $pdo->prepare(
        "SELECT id FROM conversations WHERE id = ? AND (employer_id = ? OR student_id = ?)"
    );
    $stmt->execute([$conv_id, $user['id'], $user['id']]);
    if (!$stmt->fetch()) err('Unauthorized', 403);

    $pdo->prepare(
        "INSERT INTO messages (conversation_id, sender_id, content, msg_type) VALUES (?,?,?,?)"
    )->execute([$conv_id, $user['id'], $content, $body['msg_type'] ?? 'text']);

    ok(['message_id' => $pdo->lastInsertId()]);
}

if ($method === 'GET' && strpos($uri, '/chat/get') !== false) {
    $conv_id = $_GET['conversation_id'] ?? null;
    if (!$conv_id) err('conversation_id required');

    $stmt = $pdo->prepare(
        "SELECT m.*, u.role as sender_role FROM messages m
         JOIN users u ON u.id = m.sender_id
         WHERE m.conversation_id = ?
         ORDER BY m.created_at ASC LIMIT 100"
    );
    $stmt->execute([$conv_id]);
    ok($stmt->fetchAll());
}
