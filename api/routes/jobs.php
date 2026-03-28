<?php
if ($method === 'GET' && strpos($uri, '/api/jobs') !== false) {
    $wilaya = $_GET['wilaya'] ?? null;
    $q      = $_GET['q'] ?? null;
    $sql    = "SELECT j.*, u.id as employer_user_id FROM jobs j
               JOIN users u ON j.employer_id = u.id
               WHERE j.status = 'open'";
    $params = [];
    if ($wilaya) { $sql .= " AND j.wilaya = ?"; $params[] = $wilaya; }
    if ($q)      { $sql .= " AND j.title LIKE ?"; $params[] = "%$q%"; }
    $sql .= " ORDER BY j.created_at DESC LIMIT 50";

    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    ok($stmt->fetchAll());
}

if ($method === 'POST' && strpos($uri, '/api/jobs') !== false) {
    $user = requireAuth($pdo);
    if ($user['role'] !== 'employer') err('Employers only', 403);

    $title = trim($body['title'] ?? '');
    if (!$title) err('Title required');

    $stmt = $pdo->prepare(
        "INSERT INTO jobs (employer_id, title, description, category, wilaya, location,
         work_type, salary_min, salary_max, duration_days, required_skills)
         VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    );
    $stmt->execute([
        $user['id'], $title,
        $body['description'] ?? null,
        $body['category'] ?? null,
        $body['wilaya'] ?? null,
        $body['location'] ?? null,
        $body['work_type'] ?? 'on-site',
        $body['salary_min'] ?? null,
        $body['salary_max'] ?? null,
        $body['duration_days'] ?? null,
        $body['required_skills'] ?? null
    ]);
    ok(['job_id' => $pdo->lastInsertId()]);
}