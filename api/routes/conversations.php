<?php
$user = requireAuth($pdo);

if ($method === 'POST' && strpos($uri, '/conversations') !== false) {
    $student = $body['student_id'];
    $job     = $body['job_id'] ?? null;

    $pdo->prepare(
        "INSERT INTO conversations (employer_id,student_id,job_id)
         VALUES (?,?,?)"
    )->execute([$user['id'],$student,$job]);

    ok(['conversation_id'=>$pdo->lastInsertId()]);
}

if ($method === 'GET' && strpos($uri, '/conversations') !== false) {
    $stmt = $pdo->prepare(
        "SELECT * FROM conversations
         WHERE employer_id=? OR student_id=?"
    );
    $stmt->execute([$user['id'],$user['id']]);
    ok($stmt->fetchAll());
}