#!/usr/bin/awk -f
#
# Obtiene los reportes de "task daily_progress" y "timew s ${UUID} :all" para cada actividad en la que se trabajó el día de hoy
#
# Por Emir Herrrera González
#
BEGIN{
  cmd="task daily_progress rc.defaultwidth=600"
  NR=0;

  while ((cmd | getline output) > 0){
    $0=output;
    NR=NR+1;
    if(NR>2){

    sep="";
    for (i=5; i<=NF; i++) {sep=sep" "$i;};
    print $3,$2,sep;
    time_cmd="timew s " $1
    NR2=0;
    while ((time_cmd | getline timetrack) > 0){
      NR2=NR2+1;
      if(NR2>1){
        print timetrack;
      }
    };
  }
  }
}
