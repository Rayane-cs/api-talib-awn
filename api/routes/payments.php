<?php
// Calculate fee endpoint (public)
if ($method === 'GET' && strpos($uri, '/fee/calculate') !== false) {
    $daily   = (float)($_GET['daily_salary'] ?? 0);
    $months  = (int)($_GET['months'] ?? 1);
    if (!$daily) err('daily_salary required');
    ok(calcFee($daily, $months));
}

// Release monthly payment
if ($method === 'POST' && strpos($uri, '/payments/release') !== false) {
    $user = requireAuth($pdo);
    $payment_id = $body['payment_id'] ?? null;

    $stmt = $pdo->prepare(
        "SELECT p.*, d.employer_id, d.status as deal_status
         FROM payments p JOIN deals d ON d.id = p.deal_id
         WHERE p.id = ? AND p.status = 'pending'"
    );
    $stmt->execute([$payment_id]);
    $payment = $stmt->fetch();
    if (!$payment) err('Payment not found');

    // Only employer or admin can release
    if ($user['id'] != $payment['employer_id'] && $user['role'] !== 'admin') err('Unauthorized', 403);

    // Deduct from employer escrow
    $pdo->prepare(
        "UPDATE escrow_accounts SET balance = balance - ? WHERE user_id = ?"
    )->execute([$payment['gross_amount'] + $payment['fee_amount'], $payment['employer_id']]);

    // Credit student wallet
    $pdo->prepare(
        "INSERT INTO escrow_accounts (user_id, balance) VALUES (?,?)
         ON DUPLICATE KEY UPDATE balance = balance + ?"
    )->execute([$payment['student_id'], $payment['net_amount'], $payment['net_amount']]);

    $pdo->prepare(
        "UPDATE payments SET status = 'released', paid_at = NOW() WHERE id = ?"
    )->execute([$payment_id]);

    $pdo->prepare(
        "INSERT INTO wallet_transactions (user_id, type, amount, status) VALUES (?,'release',?,'completed')"
    )->execute([$payment['student_id'], $payment['net_amount']]);

    ok(['released' => $payment['net_amount']]);
}