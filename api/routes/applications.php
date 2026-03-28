<?php
$user = requireAuth($pdo);

if ($method === 'POST' && strpos($uri, '/applications') !== false) {
    $job = $body['job_id'] ?? null;
    if(!$job) err('job_id required');

    $pdo->prepare(
        "INSERT INTO applications (job_id,student_id,cover_letter) VALUES (?,?,?)"
    )->execute([$job,$user['id'],$body['cover_letter'] ?? null]);

    ok(['applied'=>true]);
}

if ($method === 'GET' && strpos($uri, '/applications') !== false) {
    $stmt = $pdo->prepare(
        "SELECT * FROM applications WHERE student_id=? ORDER BY created_at DESC"
    );
    $stmt->execute([$user['id']]);
    ok($stmt->fetchAll());
}