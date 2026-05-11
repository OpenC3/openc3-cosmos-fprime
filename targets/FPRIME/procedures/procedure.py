# Script Runner test script
cmd("FPRIME EXAMPLE")
wait_check("FPRIME STATUS BOOL == 'FALSE'", 5)
