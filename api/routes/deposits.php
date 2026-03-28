<?php
$user = requireAuth($pdo);

if ($method === 'POST' && strpos($uri, '/deposits/create') !== false) {
    $deal_id = $body['deal_id'] ?? null;
    $stmt = $pdo->prepare(
        "SELECT d.*, af.daily_salary, af.duration_months
         FROM deals d
         LEFT JOIN agreement_forms af ON af.deal_id = d.id
         WHERE d.id = ? AND d.employer_id = ? AND d.status = 'deposit_pending'"
    );
    $stmt->execute([$deal_id, $user['id']]);
    $deal = $stmt->fetch();
    if (!$deal) err('Deal not found or already deposited');

    // Check deadline
    if (strtotime($deal['deposit_deadline']) < time()) {
        $pdo->prepare("UPDATE deals SET status = 'cancelled' WHERE id = ?")->execute([$deal_id]);
        err('Deposit deadline passed, deal cancelled');
    }

    $fee = calcFee($deal['daily_salary'], $deal['duration_months']);
    $student_total = $deal['daily_salary'] * 30 * $deal['duration_months'];
    $total = $student_total + $fee['total_fee'];

    // Record deposit
    $ref = 'DEP-' . strtoupper(bin2hex(random_bytes(8)));
    $pdo->prepare(
        "INSERT INTO deposits (deal_id, employer_id, amount, status, transaction_ref)
         VALUES (?,?,?,'confirmed',?)"
    )->execute([$deal_id, $user['id'], $total, $ref]);

    // Credit escrow
    $pdo->prepare(
        "INSERT INTO escrow_accounts (user_id, balance) VALUES (?,?)
         ON DUPLICATE KEY UPDATE balance = balance + ?"
    )->execute([$user['id'], $total, $total]);

    // Log wallet transaction
    $pdo->prepare(
        "INSERT INTO wallet_transactions (user_id, type, amount, reference, status)
         VALUES (?,'escrow',?,?,'completed')"
    )->execute([$user['id'], $total, $ref]);

    $pdo->prepare("UPDATE deals SET status = 'secured' WHERE id = ?")->execute([$deal_id]);
    ok(['deposited' => $total, 'ref' => $ref, 'status' => 'secured']);
}