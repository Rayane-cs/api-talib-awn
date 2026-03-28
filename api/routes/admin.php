<?php
$user = requireAuth($pdo);
if($user['role']!='admin') err('admin only',403);

if(strpos($uri,'/admin/users')!==false){
    ok($pdo->query("SELECT id,email,role FROM users")->fetchAll());
}

if(strpos($uri,'/admin/deals')!==false){
    ok($pdo->query("SELECT * FROM deals")->fetchAll());
}

if(strpos($uri,'/admin/ban-user')!==false){
    $id=$body['user_id'];
    $pdo->prepare("UPDATE users SET is_banned=1 WHERE id=?")->execute([$id]);
    ok(['banned'=>true]);
}