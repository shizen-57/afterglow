import test from 'node:test';
import assert from 'node:assert/strict';
import {calendarSummary,selectObservations,selectedEstimate} from '../src/data.js';
test('historical calendar counts and models agree with the active filters across periods',()=>{
  const rows=[
    {year:2023,period:0,district:'Sylhet',satellite:'Terra'},
    {year:2023,period:0,district:'Sylhet',satellite:'NOAA-20'},
    {year:2023,period:1,district:'Dhaka',satellite:'NOAA-20'},
    {year:2024,period:45,district:'Sylhet',satellite:'NOAA-20',lowConfidence:true},
    {year:2024,period:45,district:'Sylhet',satellite:'NOAA-20',excluded:true},
  ];
  const models=[{year:2023,period:0,district:'Sylhet',value:4,grounded:{value:3}},{year:2024,period:45,district:'Sylhet',value:2}];
  for(const area of ['Bangladesh','Sylhet'])for(const grounded of [false,true])for(const satellite of [null,'NOAA-20'])for(const includeLow of [false,true])for(const includeExcluded of [false,true]){
    const state={area,grounded,satellite,includeLow,includeExcluded};
    const summary=calendarSummary(rows,models,state);
    for(const [year,period] of [[2023,0],[2023,1],[2024,45]]){
      const selection={...state,year,period},key=`${year}|${period}`;
      assert.equal(summary.counts.get(key)||0,selectObservations(rows,selection).length);
      assert.deepEqual(summary.models.get(key)||null,selectedEstimate(models,selection)||null);
    }
  }
});
