<?php
require '../config/db.php';

$pdo->query("
UPDATE deals 
SET status='cancelled'
WHERE status='deposit_pending'
AND deposit_deadline < NOW()
");