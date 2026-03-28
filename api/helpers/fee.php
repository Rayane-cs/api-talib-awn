<?php
function calcFee($daily_salary, $months = 1) {
    if ($daily_salary < 1000) {
        $fee_per_month = 150;
        $type = 'fixed';
    } else {
        $fee_per_month = round($daily_salary * 0.30, 2);
        $type = 'percentage';
    }
    return [
        'fee_per_month' => $fee_per_month,
        'total_fee'     => $fee_per_month * $months,
        'type'          => $type
    ];
}