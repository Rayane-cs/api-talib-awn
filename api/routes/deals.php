<?php
$user = requireAuth($pdo);

// Start deal
if ($method === 'POST' && strpos($uri, '/deals/start') !== false) {
    $conv_id = $body['conversation_id'] ?? null;
    if (!$conv_id) err('conversation_id required');

    // Get conversation
    $stmt = $pdo->prepare("SELECT * FROM conversations WHERE id = ? AND employer_id = ?");
    $stmt->execute([$conv_id, $user['id']]);
    $conv = $stmt->fetch();
    if (!$conv) err('Unauthorized or conversation not found', 403);

    // Check no active deal
    $stmt = $pdo->prepare("SELECT id FROM deals WHERE conversation_id = ? AND status != 'cancelled'");
    $stmt->execute([$conv_id]);
    if ($stmt->fetch()) err('Active deal already exists');

    $stmt = $pdo->prepare(
        "INSERT INTO deals (conversation_id, employer_id, student_id, status)
         VALUES (?, ?, ?, 'employer_started')"
    );
    $stmt->execute([$conv_id, $user['id'], $conv['student_id']]);
    ok(['deal_id' => $pdo->lastInsertId()]);
}

// Accept deal
if ($method === 'POST' && strpos($uri, '/deals/accept') !== false) {
    $deal_id = $body['deal_id'] ?? null;
    $stmt = $pdo->prepare(
        "SELECT * FROM deals WHERE id = ? AND student_id = ? AND status = 'employer_started'"
    );
    $stmt->execute([$deal_id, $user['id']]);
    $deal = $stmt->fetch();
    if (!$deal) err('Deal not found or cannot accept');

    // Create agreement form
    $pdo->prepare("INSERT INTO agreement_forms (deal_id) VALUES (?)")->execute([$deal_id]);
    $pdo->prepare("UPDATE deals SET status = 'form' WHERE id = ?")->execute([$deal_id]);
    ok(['status' => 'form']);
}

// Confirm deal
if ($method === 'POST' && strpos($uri, '/deals/confirm') !== false) {
    $deal_id = $body['deal_id'] ?? null;
    $stmt = $pdo->prepare("SELECT * FROM deals WHERE id = ? AND status = 'form'");
    $stmt->execute([$deal_id]);
    $deal = $stmt->fetch();
    if (!$deal) err('Deal not in form stage');

    $is_employer = ($user['id'] == $deal['employer_id']);
    $is_student  = ($user['id'] == $deal['student_id']);
    if (!$is_employer && !$is_student) err('Unauthorized', 403);

    $field = $is_employer ? 'employer_confirmed' : 'student_confirmed';
    $pdo->prepare("UPDATE deals SET $field = 1 WHERE id = ?")->execute([$deal_id]);

    // Re-fetch
    $stmt = $pdo->prepare("SELECT employer_confirmed, student_confirmed FROM deals WHERE id = ?");
    $stmt->execute([$deal_id]);
    $d = $stmt->fetch();

    if ($d['employer_confirmed'] && $d['student_confirmed']) {
        $deadline = date('Y-m-d H:i:s', time() + 86400);
        $pdo->prepare(
            "UPDATE deals SET status = 'deposit_pending', deposit_deadline = ? WHERE id = ?"
        )->execute([$deadline, $deal_id]);

        // Create payment schedule
        $stmt = $pdo->prepare("SELECT * FROM agreement_forms WHERE deal_id = ?");
        $stmt->execute([$deal_id]);
        $form = $stmt->fetch();
        if ($form) {
            $fee = calcFee($form['daily_salary'], $form['duration_months']);
            $monthly_gross = $form['daily_salary'] * 30;
            for ($m = 1; $m <= $form['duration_months']; $m++) {
                $pdo->prepare(
                    "INSERT INTO payments (deal_id, student_id, month_number, gross_amount, fee_amount, net_amount)
                     VALUES (?,?,?,?,?,?)"
                )->execute([
                    $deal_id, $deal['student_id'], $m,
                    $monthly_gross, $fee['fee_per_month'],
                    $monthly_gross  // student gets full amount
                ]);
                $pdo->prepare(
                    "INSERT INTO platform_fees (deal_id, month_number, daily_salary, fee_amount, fee_type)
                     VALUES (?,?,?,?,?)"
                )->execute([
                    $deal_id, $m, $form['daily_salary'],
                    $fee['fee_per_month'], $fee['type']
                ]);
            }
        }
        ok(['status' => 'deposit_pending', 'deadline' => $deadline]);
    }
    ok(['status' => 'waiting_other_party']);
}