# MPS 业务逻辑 Check-list（SDD 基准清单）

说明：每条规则对应至少一个测试用例；测试命名 `tests/mps/test_kernel_<分类>.py::test_<编号小写>_<简述>`；状态：待实现 / 通过 / 阻塞(疑点)。

## 分类编码
- CALC 核算公式（周期/成品率/投料/通量/瓶颈）
- CYCLE 周期类（单件/加急/分部件/爬坡）
- YIELD 成品率/放量比/投料量
- FLUX 通量/瓶颈/DB-WB分流/折算系数
- DELIVERY 交付周期/最晚投料日/缓冲
- LOAD 周负荷/瓶颈占用/判定阈值
- PRIO 优先级引擎
- SCHED 排产约束
- SYNC 明道云映射与同步
- DB 双库与数据一致性
- UI 前端视图行为
- COL V1.7 清单列解读（成品率/放量比/周期三列/特征列组/爬坡与事件列/瓶颈列/批量周期四口径/周计划输出列）

## 清单

| 编号 | 规则描述 | 来源 | 预期结果 | 测试用例 | 状态 |
|---|---|---|---|---|---|
| CALC-01 | M02-2D 完整算例·周期与通量：路线 DB-WB-调试-封盖前终检-封盖，单件周期 T=1+1+1+1+2−0=6天（加急4天）；参考批量1000≥20→自动DB：6000÷60=100只/天（峰值110）；自动WB：12000÷60=200只/天→瓶颈为DB | V1.6 §九 完整算例（表6） | T单件=6天、加急=4天；采用通量=100只/天；瓶颈工序=DB | tests/mps/test_kernel_calc.py::test_calc_01_m02_2d_cycle_flux | 待实现 |
| CALC-02 | M02-2D 完整算例·成品率与投料交付链：成品率 0.97×0.99×1×0.995×0.995=0.9507→放量比1.052→投料量⌈1000×1.052⌉=1052只；批量周期 6+⌈(1052−100)/100⌉=16天；瓶颈占用⌈1052÷100⌉=11天；交付 16+0+1=17天；交期12/31→最晚投料12/14 | V1.6 §九 完整算例（表6） | 放量比1.052、投料1052、批量周期16、瓶颈占用11、交付17、最晚投料12/14 | tests/mps/test_kernel_calc.py::test_calc_02_m02_2d_yield_feed_delivery | 待实现 |
| CALC-03 | 同周 M01-2DS（500只/首单，N_smt=24、N_die=60、N_wire=300）周负荷算例：模块级DB（自动）94860÷36000→2.64"超载"；模块级WB（自动）221820÷72000→3.08"超载"；模块级SMT 12696÷14400→0.88"偏紧" | V1.6 §九 完整算例（第二段） | 三条负荷率与判定标签复现；DB/WB提示拆批或加班、SMT预警 | tests/mps/test_kernel_calc.py::test_calc_03_m01_2ds_weekly_load | 待实现 |
| CYCLE-01 | 单件装配周期构成：T单件=Σ（路线各工序装配周期）+前置分部件装配周期（仅C系列组件类）；爬坡时间不计入单件周期 | V1.6 §三 装配周期计算逻辑；§六 | M02-2D 5道工序→6天；含前置分部件的组件工艺=Σ工序周期+前置分部件周期 | tests/mps/test_kernel_cycle.py::test_cycle_01_single_piece_sum | 待实现 |
| CYCLE-02 | 分部件规则：M系列分部件（如M10-POP上基板、M11-P2P上模块、M07-CHP载片块）为平行结构，不占主体成套工艺周期；C系列（如含PCBA分部件，C02-ME2等）为前置结构，计入周期 | V1.6 §一（V1.6变化②：M系列平行不占周期、C系列前置计入周期）；表7 | 平行分部件不增加T单件；前置分部件增加T单件 | tests/mps/test_kernel_cycle.py::test_cycle_02_parallel_subparts_excluded | 待实现 |
| CYCLE-03 | 加急周期压缩分段（按T单件所在区间）：ΔT≤5天→压缩1天；6~10天→压缩2天；>10天→压缩3天 | V1.6 §三（加急口径）；表6算例（6天→4天） | T=5→加急4；T=6→加急4；T=11→加急8 | tests/mps/test_kernel_cycle.py::test_cycle_03_urgent_delta_tiers | 待实现 |
| CYCLE-04 | 加急压缩下限：压缩后周期不低于1天 | V1.6 §三（加急口径补充） | T=1、2天时加急周期≥1天 | tests/mps/test_kernel_cycle.py::test_cycle_04_urgent_min_one_day | 待实现 |
| CYCLE-05 | 封盖类工序（模块级封盖、组件级激光封盖）在"无水汽含量要求"时，装配周期由2天减为1天 | V1.6 §三；样本字段「有无水汽含量要求(有/无)」 | 有水汽→封盖2天；无水汽→封盖1天 | tests/mps/test_kernel_cycle.py::test_cycle_05_lid_no_moisture_reduce | 待实现 |
| CYCLE-06 | 爬坡时间事件触发：仅新品首产/停线复线/工艺变更首件时启用；常规滚动订单取0 | V1.6 §三/§六；样本字段「是否首单/复线/变更首件(否/首单/复线/变更首件)」 | 首单/复线/变更首件→取爬坡时间；常规→0 | tests/mps/test_kernel_cycle.py::test_cycle_06_rampup_trigger | 待实现 |
| CYCLE-07 | 爬坡时间取值：芯片级/模块级=1天（含二维/三维模块、载片块、PCBA）；组件级=2天 | V1.6 §六；§一（③爬坡时间调整） | M01-2DS首单+1天；C01-ME1首单+2天 | tests/mps/test_kernel_cycle.py::test_cycle_07_rampup_days_by_level | 待实现 |
| CYCLE-08 | 爬坡期有效通量=基准通量×MIN(1, t/爬坡时间)；仅用于产能校验折算，不影响单件装配周期 | V1.6 §六 | t=0.5×爬坡时间时通量折半；单件周期不变 | tests/mps/test_kernel_cycle.py::test_cycle_08_rampup_flux_min_ratio | 待实现 |
| YIELD-01 | 成品率链：成套工艺成品率 Y=Π（各工序综合成品率） | V1.6 §成品率与装配放量比；表6 | M02-2D：0.97×0.99×1×0.995×0.995=0.9507 | tests/mps/test_kernel_yield.py::test_yield_01_chain_product | 待实现 |
| YIELD-02 | 成品率口径：仅"工序综合成品率"纳入计算（维护于主数据H列）；一次装配合格率、一次检验合格率不纳入计算，仅存档 | V1.6 表格3（合格率字段纳入性） | 放量比中不含一次装配/一次检验合格率 | tests/mps/test_kernel_yield.py::test_yield_02_only_composite_rate | 待实现 |
| YIELD-03 | 装配放量比=1/Y | V1.6 §成品率与装配放量比 | Y=0.9507→放量比1.052 | tests/mps/test_kernel_yield.py::test_yield_03_ratio_inverse | 待实现 |
| YIELD-04 | 投料量=⌈计划批量×放量比⌉ | V1.6 §成品率与装配放量比；表6 | ⌈1000×1.052⌉=1052只 | tests/mps/test_kernel_yield.py::test_yield_04_feed_ceil | 待实现 |
| YIELD-05 | 产出校核迭代：预期产出=投料量×成品率≥计划批量；不足则放大投料量迭代 | V1.6 §成品率与装配放量比；§八⑤ | 产出<批量时投料量上调并重算直至产出≥批量 | tests/mps/test_kernel_yield.py::test_yield_05_output_check_iterate | 待实现 |
| YIELD-06 | 组件钎焊工序良率不纳入装配放量比计算（组件放量比只计算DB、WB、调试等工序）【疑点另记】 | V1.6 §成品率与装配放量比（组件钎焊剔除规则） | 组件成品率链剔除钎焊良率；与通用Π口径的差异需单独记录 | tests/mps/test_kernel_yield.py::test_yield_06_component_braze_excluded | 阻塞(疑点) |
| FLUX-01 | 工序基准均值通量=单工位日产能×工位数（工序特征量/天） | V1.6 §五 5.1 | 单工位产能×工位数，单位=工序核算特征单位/天 | tests/mps/test_kernel_flux.py::test_flux_01_base_mean_flux | 待实现 |
| FLUX-02 | 工序基准峰值通量=基准均值通量×峰值系数1.1 | V1.6 §五 5.1 | M02-2D DB：100只/天→峰值110只/天 | tests/mps/test_kernel_flux.py::test_flux_02_peak_flux_1_1 | 待实现 |
| FLUX-03 | 工序产能计量特征单位：植球N_b、倒装N_fc、SMT N_smt、DB N_die、WB N_wire、电装N_a（焊点+螺钉）、钎焊N_BS；调试/终检/封盖/叠层/底填/测试按只产品N | V1.6 §五 5.1；样本字段N_b/N_fc/N_smt/N_die/N_wire/N_bs/N_a | 各工序按对应特征计量，取错特征即出数错误 | tests/mps/test_kernel_flux.py::test_flux_03_feature_units | 待实现 |
| FLUX-04 | 产品级通量（只产品/天）=工序基准通量×折算系数÷单只产品特征用量N_x（折算系数默认1.0，≥2种时按Y_die/Y_wire） | V1.6 §五 5.3 | 自动DB：6000÷60=100只/天 | tests/mps/test_kernel_flux.py::test_flux_04_product_flux_formula | 待实现 |
| FLUX-05 | 特征为"只产品N"的工序直接取用基准通量（不除以N_x） | V1.6 §五 5.3 | 调试/终检/封盖类通量=基准通量 | tests/mps/test_kernel_flux.py::test_flux_05_only_product_take_base | 待实现 |
| FLUX-06 | DB使用两种以上类型胶水时触发折算：有效通量=折算后通量×Y_die | V1.6 §五 5.3；样本字段「DB/胶水类型数」 | 类型数=1→不折算；≥2→乘Y_die | tests/mps/test_kernel_flux.py::test_flux_06_db_coeff_trigger | 待实现 |
| FLUX-07 | Y_die取值：胶水2种→0.9；3种→0.8；1种→1.0 | V1.6 §五 5.3（Y_die取值规则） | 2种→×0.9；3种→×0.8 | tests/mps/test_kernel_flux.py::test_flux_07_db_coeff_values | 待实现 |
| FLUX-08 | WB使用两种以上规格引线时触发折算：引线2种→Y_wire=0.95；3种→0.9；1种→1.0 | V1.6 §五 5.3（Y_wire取值规则）；样本字段「WB/引线类型数」 | 2种→×0.95；3种→×0.9 | tests/mps/test_kernel_flux.py::test_flux_08_wb_coeff_values | 待实现 |
| FLUX-09 | 生产模式分流·模块级DB：参考批量＜20只→半自动2000芯片/天；≥20只→自动6000芯片/天 | V1.6 表格4（生产模式分流） | 参考批量1000→自动6000芯片/天 | tests/mps/test_kernel_flux.py::test_flux_09_db_mode_split_module | 待实现 |
| FLUX-10 | 生产模式分流·模块级WB：＜20只→半自动4500根丝/天；≥20只→自动档（自动通量取值见FLUX-15A/15B疑点） | V1.6 表格4（生产模式分流） | 参考批量1000→自动档；同阈值20只与DB一致 | tests/mps/test_kernel_flux.py::test_flux_10_wb_mode_split_module | 待实现 |
| FLUX-11 | 生产模式分流·组件级：DB 1600/4000芯片/天、WB 4000/10000根丝/天（半自动/自动）；阈值＜10只→半自动，≥10只→自动 | V1.6 表格4；§八⑤ | 批量18只→半自动；批量100只→自动 | tests/mps/test_kernel_flux.py::test_flux_11_mode_split_component | 待实现 |
| FLUX-12 | 参考批量=1000只（MPS计算逻辑参数表D列，默认），用于基准通量模式判定；周计划负荷按订单实际批量动态分流 | V1.6 §五 5.2；表格5（参考批量维护位置） | 基准档按1000判定；周负荷按各订单实际批量各自分流 | tests/mps/test_kernel_flux.py::test_flux_12_ref_batch_1000 | 待实现 |
| FLUX-13 | 产品基准通量=MIN（路线各工序产品级均值通量）；瓶颈=取小工序，底表G列自动标出瓶颈工序 | V1.6 §五 5.4（E/F列MINIFS取小、G列瓶颈工序） | M02-2D：DB 100<WB 200→瓶颈=DB | tests/mps/test_kernel_flux.py::test_flux_13_bottleneck_min | 待实现 |
| FLUX-14 | 缺BOM特征参数时，仅"只产品N"类工序参与取小，H列提示"缺BOM特征参数" | V1.6 §五 5.4；§八④ | 未录特征时取小结果仅含只产品类工序并输出缺参提示 | tests/mps/test_kernel_flux.py::test_flux_14_missing_feature_excluded | 待实现 |
| FLUX-15A | 疑点·模块级WB自动通量取值A：12000根丝/天（V1.6 口径） | V1.6 表格4 | WB自动通量=12000，产品级通量=12000÷N_wire | tests/mps/test_kernel_flux.py::test_flux_15a_wb_auto_12000 | 阻塞(疑点) |
| FLUX-15B | 疑点·模块级WB自动通量取值B：20000根丝/天 | 疑点登记（与V1.6表格4不一致，出处待核实） | WB自动通量=20000，产品级通量=20000÷N_wire | tests/mps/test_kernel_flux.py::test_flux_15b_wb_auto_20000 | 阻塞(疑点) |
| DELIVERY-01 | 批量总装配周期=T单件+批量项（投料量口径） | V1.6 §三（批量总装配周期）；表6 | M02-2D：6+10=16天 | tests/mps/test_kernel_delivery.py::test_delivery_01_batch_cycle_sum | 待实现 |
| DELIVERY-02 | 批量项=(投料量−瓶颈通量)÷瓶颈通量；计算为负时取0 | V1.6 表6（批量项算式）；负值取0为口径补充 | 投料量≤瓶颈通量→批量项=0 | tests/mps/test_kernel_delivery.py::test_delivery_02_batch_term_formula | 待实现 |
| DELIVERY-03A | 疑点·批量项取整取值A：向上取整⌈⌉（V1.6 算例口径）→6+⌈9.52⌉=16天 | V1.6 §九 表6（⌈(1052−100)/100⌉） | M02-2D 批量周期=16天 | tests/mps/test_kernel_delivery.py::test_delivery_03a_batch_term_ceil | 阻塞(疑点) |
| DELIVERY-03B | 疑点·批量项取整取值B：不取整（Excel口径）→6+9.52=15.52天 | 疑点登记（Excel不取整口径） | M02-2D 批量周期=15.52天 | tests/mps/test_kernel_delivery.py::test_delivery_03b_batch_term_no_ceil | 阻塞(疑点) |
| DELIVERY-04 | 交付周期=批量总装配周期+爬坡时间（仅首单/复线/变更首件，常规=0）+订单缓冲（默认1天） | V1.6 §六（交付周期公式） | M02-2D常规：16+0+1=17天；首单：16+1+1=18天 | tests/mps/test_kernel_delivery.py::test_delivery_04_delivery_cycle_formula | 待实现 |
| DELIVERY-05A | 疑点·订单缓冲取值A：计入默认1天缓冲（V1.6 口径） | V1.6 §六（订单缓冲默认1天） | 交付周期含+1天 | tests/mps/test_kernel_delivery.py::test_delivery_05a_buffer_included | 阻塞(疑点) |
| DELIVERY-05B | 疑点·订单缓冲取值B：不计入缓冲（0天） | 疑点登记（缓冲不计入口径） | 交付周期不含缓冲天数 | tests/mps/test_kernel_delivery.py::test_delivery_05b_buffer_excluded | 阻塞(疑点) |
| DELIVERY-06 | 最晚投料日=要求交期−交付周期 | V1.6 §六；§八② | 交期2026-12-31、交付17天→最晚投料2026-12-14 | tests/mps/test_kernel_delivery.py::test_delivery_06_latest_start_date | 待实现 |
| DELIVERY-07 | 最晚投料日晚于本周的排入下周 | V1.6 §八② | 超出本周的订单顺延标记至下周排产 | tests/mps/test_kernel_delivery.py::test_delivery_07_overflow_next_week | 待实现 |
| DELIVERY-08 | 加急订单周期压缩口径：T单件取加急值（M02-2D 6→4天），交付周期与最晚投料日按压缩后周期计算 | V1.6 §三、表6；样本字段「订单类型(常规/加急)」 | 加急M02-2D T=4天，交付链相应提前 | tests/mps/test_kernel_delivery.py::test_delivery_08_urgent_compression | 待实现 |
| LOAD-01 | 瓶颈占用（天）=⌈投料量÷采用通量⌉ | V1.6 §八②；表6 | M02-2D：⌈1052÷100⌉=11天 | tests/mps/test_kernel_load.py::test_load_01_bottleneck_occupancy_ceil | 待实现 |
| LOAD-02 | 采用通量口径：瓶颈工序产品级基准均值通量（按工序产品装配数量折算） | V1.6 §三（瓶颈工序基准均值通量按装配数量折算）；§八② | M02-2D 采用通量=100只/天 | tests/mps/test_kernel_load.py::test_load_02_adopted_flux_mean | 待实现 |
| LOAD-03 | 周负荷=Σ（投料量×单只特征用量） | V1.6 §八③ | 同周同工序各订单投料量×特征用量求和 | tests/mps/test_kernel_load.py::test_load_03_weekly_load_sum | 待实现 |
| LOAD-04 | 周负荷汇总匹配口径：按产品级别+规范工序名匹配工序列；仅统计路线含该工序的订单 | V1.6 §八③（汇总区按28道工序输出） | 路线不含DB的订单不计入DB列负荷 | tests/mps/test_kernel_load.py::test_load_04_route_match_scope | 待实现 |
| LOAD-05 | 周可用=工序基准均值通量×周工作天数（默认6天，参数区七维护） | V1.6 §八③；表格5（周工作天数维护位置） | 模块级DB自动：6000×6=36000 | tests/mps/test_kernel_load.py::test_load_05_weekly_capacity_6d | 待实现 |
| LOAD-06 | 负荷率=周负荷÷周可用 | V1.6 §八③ | 94860÷36000=2.64 | tests/mps/test_kernel_load.py::test_load_06_load_ratio | 待实现 |
| LOAD-07 | 判定规则：负荷率＞100%→"超载"（拆批/加班/外协） | V1.6 §八④ | 264%→标"超载" | tests/mps/test_kernel_load.py::test_load_07_overload_gt_100 | 待实现 |
| LOAD-08 | 判定规则：85%~100%→"偏紧"（预警） | V1.6 §八④ | 88%→标"偏紧"并预警 | tests/mps/test_kernel_load.py::test_load_08_tight_85_100 | 待实现 |
| LOAD-09 | 判定规则：＜85%→"正常" | V1.6 §八④ | 50%→标"正常" | tests/mps/test_kernel_load.py::test_load_09_normal_lt_85 | 待实现 |
| LOAD-10 | 缺BOM特征参数的工序自动提示"缺特征参数"，需在所属级别核算表补录 | V1.6 §八④；§五 5.4 | 缺参工序输出提示文案 | tests/mps/test_kernel_load.py::test_load_10_missing_feature_hint | 待实现 |
| CALC-04 | 数据流联动：上游参数（产线工序主数据/核算数据库/逻辑底表/参数表）修改后，下游（清单/周计划）指标自动刷新；以工艺代号为主键一次维护、全表联动 | V1.6 §一/§八（参数维护职责与数据流，表格5） | 修改工序主数据后，清单周期/通量/周负荷按链联动重算 | tests/mps/test_kernel_calc.py::test_calc_04_dataflow_propagation | 待实现 |
| CYCLE-09A | 疑点·爬坡触发口径A：新品首产/停线复线/工艺变更首件三类事件均触发（V1.6 §三/§六、V1.7 逻辑⑦；参数 ramp_trigger 档一） | V1.6 §三/§六；V1.7 逻辑⑦；样本字段「是否首单/复线/变更首件」 | 首单/复线/变更首件均加爬坡时间；常规滚动订单=0 | tests/mps/test_kernel_cycle.py::test_cycle_09a_ramp_three_events | 阻塞(疑点) |
| CYCLE-09B | 疑点·爬坡触发口径B：仅首单触发（V1.7 计算器口径"事件触发：仅首单启用，常规/加急取0"） | V1.7 §六（批量装配周期计算器爬坡行） | 仅首单加爬坡时间；复线/变更首件取0 | tests/mps/test_kernel_cycle.py::test_cycle_09b_ramp_first_only | 阻塞(疑点) |
| FLUX-16A | 疑点·BOM特征数据源A：工单行（样本24列逐单携带 N_b~N_a 与胶水/引线类型数；设计规格 D13 首版存工单行） | 样本24列字段；设计规格 D13/§4 order | 特征从工单行读取，缺列时才提示缺参 | tests/mps/test_kernel_flux.py::test_flux_16a_features_from_order_row | 阻塞(疑点) |
| FLUX-16B | 疑点·BOM特征数据源B：采集表（V1.6 §5.3/表格5、V1.7 逻辑注：特征按产品级别录入●装配周期核算表，工单行不携带） | V1.6 §5.3（表格5）；V1.7 逻辑注（"缺BOM特征参数"提示） | 特征从采集表按产品匹配，未录工序提示「缺BOM特征参数」 | tests/mps/test_kernel_flux.py::test_flux_16b_features_from_collection | 阻塞(疑点) |
| FLUX-17 | 第2组特征列：N_die-2/DB第2组胶水类型数/N_wire-2/WB第2组引线类型数随工单行导入，按组折算（Y_die2/Y_wire2；M10-POP 等双组工艺） | 样本24列（第2组特征）；计划1 特征别名表 | 双组特征各自参与对应组通量折算 | tests/mps/test_kernel_flux.py::test_flux_17_second_group_features | 待实现 |
| PRIO-01 | 排产优先级字段：整数、数字越小越优先、0=置顶（样本第10列「排产优先级(数字越小越优先)」→ order.priority） | 样本24列；设计规格 §4 order | 数值升序可比较；0 视为置顶 | tests/mps/test_kernel_prio.py::test_prio_01_priority_numeric_order | 待实现 |
| PRIO-02 | 物料齐套时间字段：样本第9列 → order.kit_date，作为排产最早开工输入（约束语义见 SCHED-04） | 样本24列；设计规格 §4 order | 齐套日期正确入库并供排产读取 | tests/mps/test_kernel_prio.py::test_prio_02_kitting_date_field | 待实现 |
| PRIO-03 | 优先级引擎 6 因子评分：自动计算 prio_score（1:1 移植 mps-web priority.js） | 设计规格 D8/§3；计划1 order 模型字段 | 评分字段生成且可复算 | tests/mps/test_kernel_prio.py::test_prio_03_six_factor_score | 待实现 |
| PRIO-04 | 优先级级别 P0~P3：评分映射级别（prio_level）并在工单管理页展示 | 设计规格 D8/§8① | 评分→级别映射一致 | tests/mps/test_kernel_prio.py::test_prio_04_p0_p3_level | 待实现 |
| PRIO-05 | 置顶机制：pinned 置顶、pinned_until 到期失效，记录 pinned_at/pinned_by | 设计规格 D8；计划1 order 字段 | 置顶期间排序最前，到期自动恢复 | tests/mps/test_kernel_prio.py::test_prio_05_pin_until | 待实现 |
| PRIO-06 | 拖拽排序：sort_no 浮点序号持久化，拖拽后顺序稳定 | 设计规格 D8；计划1 order 字段 | 拖拽顺序入库且可复现 | tests/mps/test_kernel_prio.py::test_prio_06_drag_sort_no | 待实现 |
| PRIO-07 | 优先级变更审计日志：priority_log 记录原/新优先级、原/新拖拽序、操作人与时间 | 设计规格 D8；计划1 priority_log 模型 | 每次变更留痕、可追溯 | tests/mps/test_kernel_prio.py::test_prio_07_priority_audit_log | 待实现 |
| PRIO-08 | 优先级批量操作快照：priority_batch 支持批量撤销 | 设计规格 D8；计划1 priority_batch 模型 | 批量变更可整体撤销 | tests/mps/test_kernel_prio.py::test_prio_08_batch_undo_snapshot | 待实现 |
| PRIO-09 | 排产优先级双向同步：拉取工单携带优先级、推送回写工单表单「排产优先级」 | 设计规格 D8/§7（回写清单） | 同步往返数值一致 | tests/mps/test_kernel_prio.py::test_prio_09_priority_hap_sync | 待实现 |
| PRIO-10 | 疑点·优先级与齐套/交期的组合排序语义：优先级、齐套时间、交期三者先后与跨齐套排序规则在 MPS 逻辑书与设计规格中均未定义 | 疑点登记（逻辑书未定义） | 待业务确认排产排序函数；先按参数双档实现 | tests/mps/test_kernel_prio.py::test_prio_10_priority_kitting_semantics | 阻塞(疑点) |
| SCHED-01 | 工序串行：同一工单工序级需求按「依赖前道ID」顺序执行，前道未完成不排后道 | 设计规格 §3（工序串行）/§4 order_operation | 解码结果满足串行依赖、无跨序开工 | tests/mps/test_kernel_sched.py::test_sched_01_operation_serial_dependency | 待实现 |
| SCHED-02 | 按日产能账本分配：每日分配数量不超过资源（级别\|工序\|模式）日产能 | 设计规格 §3（解码执行层） | 任意资源任一日累计分配≤日产能 | tests/mps/test_kernel_sched.py::test_sched_02_daily_capacity_ledger | 待实现 |
| SCHED-03 | 解码分流按订单实际批量动态判定（DB/WB 模块级20只/组件级10只阈值），不以参考批量1000判定 | V1.7 逻辑⑦⑪、周计划⑤；V1.6 §5.2 | 实际批量<阈值走半自动、≥阈值走自动 | tests/mps/test_kernel_sched.py::test_sched_03_mode_by_actual_batch | 待实现 |
| SCHED-04 | 齐套门槛：订单开工不早于物料齐套时间（硬约束，罚函数或修复实现） | 设计规格 §3（硬约束含齐套） | 齐套日之前的日期无分配 | tests/mps/test_kernel_sched.py::test_sched_04_kitting_gate | 待实现 |
| SCHED-05 | 分部件调度：M系列平行分部件并行生产不占主体周期；C系列前置分部件先于主体执行 | V1.7 逻辑③；设计规格 §8④ | 甘特呈现平行条/前置条且时序正确 | tests/mps/test_kernel_sched.py::test_sched_05_subpart_parallel_prepose | 待实现 |
| SCHED-06 | 返工/试制=追加工序级需求：既有工单手工新增工序需求（来源=手工追加），参与排产并占产能 | 设计规格 D12/§4/§8① | 追加需求生成、可排产 | tests/mps/test_kernel_sched.py::test_sched_06_rework_extra_operation | 待实现 |
| SCHED-07 | 换型/setup 天数纳入解码执行层（换线矩阵/换型天数参与资源占用） | 设计规格 §3（setup 天数） | 换型时按 setup 天数占用资源 | tests/mps/test_kernel_sched.py::test_sched_07_setup_days | 待实现 |
| SCHED-08 | 硬约束零违反：GA 罚函数/修复保证「产能不超、齐套、串行」零违反（验收口径） | 设计规格 §3/§10 验收2 | 任意批次结果硬约束零违反 | tests/mps/test_kernel_sched.py::test_sched_08_hard_constraints_zero_violation | 待实现 |
| SCHED-09 | 确定性基准：GA 关闭/无解时退化为确定性基准，输出与 mps-web 一致（验收对照） | 设计规格 D11/§3 | 基准模式输出与 mps-web schedule.js 一致 | tests/mps/test_kernel_sched.py::test_sched_09_deterministic_baseline | 待实现 |
| SCHED-10 | 排产批次与结果落库：schedule_batch（参数快照/KPI）与 schedule_result（每日分配明细、开始/完成日、瓶颈标记），支持历史/对比/推送 | 设计规格 §4 | 结果完整入库、可按批次追溯 | tests/mps/test_kernel_sched.py::test_sched_10_batch_result_persistence | 待实现 |
| SYNC-01 | 映射配置流程：手动输入表单ID → 后端读表单结构 → 自动匹配（按中文名/别名相似度+置信度）→ 手动调整个别字段 → 保存入库；同步引擎从数据库读映射（去硬编码 TABLE_HAP_MAP） | 设计规格 D4/§3/§6 | 全流程走通：置信度展示、未识别字段高亮 | tests/mps/test_kernel_sync.py::test_sync_01_mapping_flow | 待实现 |
| SYNC-02 | 密钥安全：AppKey/Sign Fernet 加密存储、API 仅回 configured/updated_at、永不回显明文、修改须重新输入 | 设计规格 D5/§6 | 任意接口响应不含密钥字符 | tests/mps/test_kernel_sync.py::test_sync_02_secret_never_echoed | 待实现 |
| SYNC-03 | 双向同步：拉取工单/主数据（按 hap_row_id upsert）；推送排产结果回写工单表单（按 sync_status create/update/delete） | 设计规格 D2/D9/§7 | 拉取幂等；回写字段与映射配置一致 | tests/mps/test_kernel_sync.py::test_sync_03_bidirectional_sync | 待实现 |
| SYNC-04 | 同步可关闭纯本地：DISABLE_HAP_SYNC=1 或未配置映射→全功能纯本地可用；触发=手动+定时+排产确认后推送 | 设计规格 §5/D10/§10 验收4 | 关闭同步时系统功能不缺失 | tests/mps/test_kernel_sync.py::test_sync_04_local_only_mode | 待实现 |
| SYNC-05 | 字段转换与选项映射：选项映射JSON/关联配置/日期类型转换从映射读取（含备注等文本字段原样映射）；未配置实体=同步禁用并提示 | 设计规格 §6/§7、§4 hap_field_mapping | 选项/关联/日期/文本字段往返一致 | tests/mps/test_kernel_sync.py::test_sync_05_field_option_mapping | 待实现 |
| DB-01 | 双库适配：同一套测试在 SQLite 与 PostgreSQL 均通过（PG 测试库需 TEST_PG_URL 且地址含 test，否则跳过） | 设计规格 §5/§10 验收4；计划1 Task2 | 双后端建连/建表/用例同套通过 | tests/mps/test_database_dual.py::test_sqlite_engine_connect + test_pg_engine_connect | 待实现 |
| DB-02 | SQLite 本地自动建表（create_all 零运维）；PostgreSQL 由 Alembic 迁移管理（init_schema 对非 SQLite 不做动作） | 设计规格 §5；计划1 Task2 | SQLite 启动即建表；PG 不走 create_all | tests/mps/test_database_dual.py::test_mps_tables_created | 待实现 |
| DB-03 | 种子幂等：三张主数据表清空重插；系统参数只补缺失、不覆盖用户已改值；演示工单仅在 orders 为空时导入一次 | 计划1 Task7（种子加载器） | 重复导入行数稳定、参数保留 | tests/mps/test_seed_loader.py::test_seed_idempotent_and_params_preserved | 待实现 |
| DB-04 | 可移植类型与统一出箱字段：不使用 PG 专有类型（Uuid 字符串/JSON/DateTime）；模型统一带 hap_row_id/sync_status/synced_at；JSON 往返与唯一约束成立 | 设计规格 §4/§5；计划1 Task2/3 | 双库类型等价、出箱字段齐备 | tests/mps/test_mps_models.py::test_order_features_json_roundtrip | 待实现 |
| UI-01 | 六视图职责：①工单管理（订单号/产品型号/工艺代号等24列内联编辑、Excel导入/模板/导出、优先级引擎UI、实时草算）②排产结果（求解模式/策略/异步进度/KPI/瓶颈卡/内联改交期齐套）③工序产能负荷（周负荷表图+每日产能折线 cap/85%/100%）④甘特图（订单级/工序级、瓶颈红条、齐套标记、分部件平行条）⑤日任务看板（日期/工序/级别/模式筛选）⑥基础数据（工序/工艺/路线/系统参数） | 设计规格 §8/§3 | 六视图关键路径走查通过 | tests/mps/test_kernel_ui.py::test_ui_01_six_views | 待实现 |
| UI-02 | 旧计划类页面替换：旧 Schedule/ScheduleResult/DataManager 由新页面替代，旧数据可删（清理脚本） | 设计规格 §1/§8/D1；计划1 Task8 | 旧页面不可达、旧数据清理可执行 | tests/mps/test_kernel_ui.py::test_ui_02_legacy_pages_replaced | 待实现 |
| UI-03 | 执行类页面冻结保留：报工/工序进度/工时保留入口并标注"待二期适配"，不接入新模型 | 设计规格 D1/§1/§8 | 页面可访问、标注冻结 | tests/mps/test_kernel_ui.py::test_ui_03_execution_pages_frozen | 待实现 |
| UI-04 | 明道云映射设置页（第⑦页）：菜单整合挂载、沿用现有 API Key 鉴权 | 设计规格 D7/§6/§8 | 设置页入口可用、鉴权生效 | tests/mps/test_kernel_ui.py::test_ui_04_mapping_page_entry | 待实现 |
| COL-01 | V1.7 列解读·主键与版本：工艺代号+版本号（V1.0/V1.1）；编码=级码(D/M/C)+两位流水+特征码，代号发布后含义不变、变更仅递增版本；MPS/物料/工时以代号关联 | V1.7 §三（编码规则）、清单产品形态~版本列 | 以代号取数、版本独立维护 | tests/mps/test_kernel_cols.py::test_col_01_code_version_key | 待实现 |
| COL-02 | V1.7 列解读·成品率/放量比列：成套工艺成品率=Π综合成品率、装配放量比=1/Y（C系列按剔钎焊口径） | V1.7 §四④⑤、清单成品率/放量比列 | 两列可复算、C系列口径一致 | tests/mps/test_kernel_cols.py::test_col_02_yield_ratio_columns | 待实现 |
| COL-03 | V1.7 列解读·周期三列：单件装配周期（含前置分部件）、加急单件周期=MAX(T−ΔT,1)、分部件装配周期（M09=4/M10=1/M11=6 平行；C02/C05/C07/C08 PCBA=1天前置） | V1.7 §四①②③、清单K/L/M列 | 三列取值与分部件规则一致 | tests/mps/test_kernel_cols.py::test_col_03_cycle_k_l_m | 待实现 |
| COL-04 | V1.7 列解读·BOM特征列组：N_b/N_fc/N_bs/N_smt/N_die/DB胶水类型/N_wire/WB引线类型/N_a（清单中部9列；工单样本另含第2组列） | V1.7 清单特征列组；样本24列 | 特征列与底表N_x/折算系数一一对应 | tests/mps/test_kernel_cols.py::test_col_04_feature_columns | 待实现 |
| COL-05 | V1.7 列解读·爬坡与事件列：生产爬坡时间列（参数表按工艺代号：D/M=1天、C=2天、C11-PCB=1天）、是否首单/复线/变更首件列、有无水汽含量要求列 | V1.7 清单列+参数表（逻辑⑦） | 三列驱动爬坡与封盖周期变体 | tests/mps/test_kernel_cols.py::test_col_05_ramp_event_columns | 待实现 |
| COL-06 | V1.7 列解读·瓶颈列：瓶颈工序识别 + 瓶颈工序基准均值通量（只/天-折算），来自参数表D~F列与第八部分底表取小 | V1.7 §四⑦、清单瓶颈两列 | 瓶颈工序与通量值可复现 | tests/mps/test_kernel_cols.py::test_col_06_bottleneck_columns | 待实现 |
| COL-07 | V1.7 列解读·批量周期四口径列：批量总装配周期-常规/-加急/-常规-无水汽要求/-加急-无水汽要求（无水汽变体=封盖类−1天） | V1.7 清单批量周期四列 | 按订单类型+水汽要求取对应列 | tests/mps/test_kernel_cols.py::test_col_07_batch_cycle_four_variants | 待实现 |
| COL-08 | V1.7 周计划列解读·订单区输出列：投料量/采用通量(均值)/瓶颈占用(天)/批量总装配周期(含爬坡)/爬坡(天)/交付周期(天)/最晚投料日；晚于本周排入下周 | V1.7 周计划订单区（逻辑⑨⑩/Step3） | 输出列口径与公式一致 | tests/mps/test_kernel_cols.py::test_col_08_weekly_plan_outputs | 待实现 |
| COL-09 | V1.7 周计划列解读·负荷列：按 N_b植球/N_fc倒装/N_die芯片/N_wire根丝/N_smt贴装/N_a电装点/N_bs钎焊部件 7列输出；汇总区按28道工序名匹配算负荷率 | V1.7 周计划负荷列与逻辑⑪ | 负荷列按特征用量计入对应工序 | tests/mps/test_kernel_cols.py::test_col_09_load_columns_28_ops | 待实现 |

## 覆盖自查

**统计**：第一部分 53 条（CALC 3 / CYCLE 8 / YIELD 6 / FLUX 16 / DELIVERY 10 / LOAD 10）；本部分 48 条（CALC +1 / CYCLE +2 / FLUX +3 / PRIO 10 / SCHED 10 / SYNC 5 / DB 4 / UI 4 / COL 9）；总计 101 条，满足 90~120。本部分阻塞(疑点) 5 条：PRIO-10、CYCLE-09A/09B、FLUX-16A/16B；其余 43 条待实现（另第一部分阻塞 7 条：YIELD-06、FLUX-15A/15B、DELIVERY-03A/03B、05A/05B）。

**a) V1.6 小节覆盖**
- 一 文档说明/五处变化 → CALC-04、CYCLE-02/07、FLUX-08/13、FLUX-16A/16B、COL-04
- 二 编码规则 → COL-01
- 三 装配周期计算逻辑（单件/前置分部件/加急/批量/爬坡/工单数量/瓶颈折算）→ CYCLE-01~07、DELIVERY-01~03、CALC-01
- 四 成品率与装配放量比（含钎焊剔除）→ YIELD-01~06
- 五 生产通量 5.1~5.4（基准/分流/折算/取小瓶颈）→ FLUX-01~15、FLUX-17、CALC-01/03
- 六 爬坡时间与交付周期 → CYCLE-06~09A/B、DELIVERY-04~05
- 七 输入信息 → PRIO-01/02、SCHED-04（样本字段条目见 c）
- 八 MPS周计划应用①~⑤ → LOAD-01~10、DELIVERY-06/07、SCHED-03、CALC-03
- 八 参数维护职责与数据流（表格5）→ CALC-04、COL-05
- 九 完整算例（表6）→ CALC-01~03、CYCLE-01/03、DELIVERY-03A
- 表格3（三率纳入性）→ YIELD-02；表格4（分流）→ FLUX-09~11、SCHED-03

**b) V1.7 列解读**：COL-01 主键与编码、COL-02 成品率/放量比、COL-03 周期三列（单件/加急/分部件）、COL-04 特征列组、COL-05 爬坡/首单/水汽、COL-06 瓶颈两列、COL-07 批量周期四口径、COL-08 周计划订单区输出、COL-09 负荷7列+28工序；V1.7 逻辑①~⑪分别由 CYCLE-01/02/03/08、YIELD、FLUX、DELIVERY-01~06、LOAD、SCHED-03、COL-08 对应覆盖。

**c) 样本 24 列字段覆盖**（订单号 → N_a）
| 样本列 | 对应条目 |
|---|---|
| 订单号 | DB-03、SYNC-03 |
| 产品型号 | UI-01 |
| 工艺代号 | COL-01、FLUX-12、SCHED-03 |
| 订单类型(常规/加急) | CYCLE-03/04、DELIVERY-08 |
| 是否首单/复线/变更首件 | CYCLE-06、CYCLE-09A/09B |
| 有无水汽含量要求 | CYCLE-05、COL-07 |
| 计划批量(只) | YIELD-04、FLUX-12 |
| 订单需求日期 | DELIVERY-06 |
| 物料齐套时间 | PRIO-02、SCHED-04 |
| 排产优先级 | PRIO-01~10 |
| 备注 | SYNC-05、UI-01 |
| N_b/单只植球数 | FLUX-03、COL-04 |
| N_fc/单只倒装元件数 | FLUX-03、COL-04 |
| N_smt/单只贴装元件数 | FLUX-03、COL-04 |
| N_die/单只芯片数 | FLUX-03、COL-04 |
| DB/胶水类型数 | FLUX-06/07、COL-04 |
| N_wire/单只键合根丝数 | FLUX-03、COL-04 |
| WB/引线类型数 | FLUX-08、COL-04 |
| N_die-2/第2组芯片数 | FLUX-17 |
| DB/第2组胶水类型数 | FLUX-17 |
| N_wire-2/第2组键合根丝数 | FLUX-17 |
| WB/第2组引线类型数 | FLUX-17 |
| N_bs/单只钎焊部件数 | FLUX-03、COL-04 |
| N_a/单只电装点数(焊点+螺钉) | FLUX-03、COL-04 |

**d) 五类疑点双档（各≥2条）**：① WB自动通量 → FLUX-15A/15B（第一部分）；② 批量项取整 → DELIVERY-03A/03B（第一部分）；③ 订单缓冲 → DELIVERY-05A/05B（第一部分）；④ 爬坡触发 → CYCLE-09A/09B（本部分，基础条目 CYCLE-06）；⑤ BOM特征数据源 → FLUX-16A/16B（本部分，基础条目 FLUX-14）。全部按 system_param 双档参数化实现（计划1 穷尽性要求4）。

**e) 总条目数**：53 + 48 = 101（90~120 达标）；编号在分类内连续唯一：CALC-04、CYCLE-09A/09B、FLUX-16A/16B、FLUX-17、PRIO-01~10、SCHED-01~10、SYNC-01~05、DB-01~04、UI-01~04、COL-01~09。
