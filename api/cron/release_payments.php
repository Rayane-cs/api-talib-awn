<?php
require '../config/db.php';

$stmt = $pdo->query("
SELECT * FROM payments
WHERE status='pending'
");

foreach($stmt as $p){

    $pdo->prepare(
        "UPDATE payments SET status='released',paid_at=NOW() WHERE id=?"
    )->execute([$p['id']]);

    $pdo->prepare(
        "UPDATE escrow_accounts
         SET balance = balance + ?
         WHERE user_id=?"
    )->execute([$p['net_amount'],$p['student_id']]);
}